# main.py

from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import asyncio
import sqlite3
import string
import random
from datetime import datetime
import httpx

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_PATH = "links.db"

# If you're pinging yourself on Render/Heroku to stay warm:
SERVICE_URL = "https://five68u96950.onrender.com"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      code TEXT UNIQUE,
      target TEXT,
      email TEXT,
      created_at TEXT
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


@app.on_event("startup")
async def startup():
    init_db()


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choices(alphabet, k=length))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/create", response_class=HTMLResponse)
async def create_link(
    request: Request,
    target_url: str = Form(...),
    shortener: str = Form(...),
    email: str = Form(...),
    capture_ip: str = Form(None),
    capture_geo: str = Form(None)
):
    # only 'random' supported for now
    code = generate_code() if shortener == "random" else shortener

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    try:
        c.execute(
            "INSERT INTO links (code,target,email,created_at) VALUES (?,?,?,?)",
            (code, target_url, email, created_at)
        )
    except sqlite3.IntegrityError:
        # collision: retry once
        code = generate_code()
        c.execute(
            "INSERT INTO links (code,target,email,created_at) VALUES (?,?,?,?)",
            (code, target_url, email, created_at)
        )
    conn.commit()
    conn.close()

    link_url  = request.url_for("redirect_to_target", code=code)
    track_url = request.url_for("track",            code=code)

    return templates.TemplateResponse(
        "result.html",
        {"request": request, "link_url": link_url, "track_url": track_url}
    )


@app.get("/{code}")
async def redirect_to_target(
    request: Request,
    code: str,
    x_forwarded_for: str | None = Header(None),
):
    # 1) lookup link
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, target FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Link not found")
    link_id, target = row

    # 2) determine real client IP
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host or ""

    ua = request.headers.get("user-agent", "")

    # 3) geolocation lookup
    country = region = city = ""
    async with httpx.AsyncClient() as client:
        try:
            # primary: ipapi.co (no trailing slash)
            r = await client.get(f"https://ipapi.co/{ip}/json", timeout=5.0)
            data = r.json()
            if r.status_code == 200 and not data.get("error"):
                country = data.get("country_name", "") or ""
                region  = data.get("region", "") or ""
                city    = data.get("city", "") or ""
            else:
                # fallback to ip-api.com
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
                    print(f"[GeoError] ip-api.com for {ip}: {d2.get('message')}")
        except Exception as e:
            print(f"[GeoException] {e!r}")

    # 4) log visit
    timestamp = datetime.utcnow().isoformat()
    c.execute(
        """
        INSERT INTO visits
          (link_id, ip, user_agent, country, region, city, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (link_id, ip, ua, country, region, city, timestamp)
    )
    conn.commit()
    conn.close()

    # 5) redirect
    return RedirectResponse(url=target)


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


# ─── Scheduled external ping ─────────────────────────────────────────────────
@app.on_event("startup")
async def schedule_ping_task():
    async def ping_loop():
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    resp = await client.get(f"{SERVICE_URL}/ping")
                    if resp.status_code != 200:
                        print(f"[Ping] returned {resp.status_code}")
                except Exception as e:
                    print(f"[PingError] {e!r}")
                await asyncio.sleep(10)
    asyncio.create_task(ping_loop())


# ─── HEALTHCHECK ───────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"status": "alive"}
