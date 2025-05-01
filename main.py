# main.py
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sqlite3
import string, random
from datetime import datetime
import httpx

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_PATH = "links.db"


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
    # only 'random' is supported for now
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
        # rare collision: try again
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
async def redirect_to_target(request: Request, code: str):
    # lookup
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id,target FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        return HTMLResponse("Link not found", status_code=404)

    link_id, target = row

    # visitor info
    ip = request.client.host or ""
    ua = request.headers.get("user-agent", "")

    # geolocation lookup
    country = region = city = ""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://ipapi.co/{ip}/json/", timeout=5.0)
            data = resp.json()
            country = data.get("country_name", "")
            region  = data.get("region", "")
            city    = data.get("city", "")
    except Exception:
        pass

    timestamp = datetime.utcnow().isoformat()
    c.execute("""
      INSERT INTO visits
      (link_id,ip,user_agent,country,region,city,timestamp)
      VALUES (?,?,?,?,?,?,?)
    """, (link_id, ip, ua, country, region, city, timestamp))
    conn.commit()
    conn.close()

    return RedirectResponse(url=target)


@app.get("/track/{code}", response_class=HTMLResponse)
async def track(request: Request, code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        return HTMLResponse("Link not found", status_code=404)
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
                        print(f"Health ping returned {resp.status_code}")
                except Exception as e:
                    print(f"External ping failed: {e!r}")
                await asyncio.sleep(10)
    asyncio.create_task(ping_loop())

# ─── HEALTHCHECK ───────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"status": "alive"}

