"""FastAPI app: web dashboard + JSON API, with the tracker running in the background."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .config import SettingsStore
from .flightaware import FlightAwareClient, FlightAwareError
from .opensky import OpenSkyClient, OpenSkyError
from .tracker import Tracker
from .vestaboard import VestaboardClient, VestaboardError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
STATIC_DIR = Path(__file__).parent / "static"
DASHBOARD_USER = os.environ.get("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
USER_AGENT = "vestaboard-overhead-planes/1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    store = SettingsStore(DATA_DIR / "settings.json")
    tracker = Tracker(store, OpenSkyClient(http), FlightAwareClient(http), VestaboardClient(http))
    app.state.http, app.state.store, app.state.tracker = http, store, tracker
    task = asyncio.create_task(tracker.run()) if os.environ.get("DISABLE_TRACKER") != "1" else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await http.aclose()


app = FastAPI(title="Vestaboard Overhead Planes", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if DASHBOARD_PASSWORD and request.url.path != "/healthz":
        ok = False
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, DASHBOARD_USER) and secrets.compare_digest(
                    password, DASHBOARD_PASSWORD
                )
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return Response(
                status_code=401, headers={"WWW-Authenticate": 'Basic realm="Overhead Planes"'}
            )
    return await call_next(request)


def tracker(request: Request) -> Tracker:
    return request.app.state.tracker


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/settings")
async def get_settings(request: Request):
    return request.app.state.store.get().masked()


@app.put("/api/settings")
async def put_settings(request: Request):
    changes = await request.json()
    if not isinstance(changes, dict):
        raise HTTPException(400, "Expected a JSON object")
    try:
        settings = request.app.state.store.update(changes)
    except ValidationError as exc:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)
    tracker(request).settings_changed()
    return settings.masked()


@app.get("/api/status")
async def status(request: Request):
    return {**tracker(request).snapshot(), "auth_enabled": bool(DASHBOARD_PASSWORD)}


@app.post("/api/refresh")
async def refresh(request: Request):
    tracker(request).wake(poll=True)
    return {"ok": True}


class ManualMessage(BaseModel):
    lines: list[str] = Field(max_length=6)
    hold_minutes: float = Field(default=5, ge=0, le=1440)


@app.post("/api/board/message")
async def board_message(request: Request, body: ManualMessage):
    try:
        await tracker(request).show_manual(body.lines, body.hold_minutes)
    except VestaboardError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


@app.post("/api/board/resume")
async def board_resume(request: Request):
    tracker(request).resume()
    return {"ok": True}


@app.post("/api/test/{service}")
async def test_service(request: Request, service: str):
    t = tracker(request)
    s = request.app.state.store.get()
    try:
        if service == "opensky":
            message = await t.opensky.test(s.opensky_client_id, s.opensky_client_secret)
        elif service == "flightaware":
            message = await t.flightaware.test(s.flightaware_api_key)
        elif service == "vestaboard":
            message = await t.board.test(s)
        else:
            raise HTTPException(404, "Unknown service")
    except (OpenSkyError, FlightAwareError, VestaboardError) as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": message}


@app.get("/api/geocode")
async def geocode(request: Request, q: str):
    """Look up an address/place with OpenStreetMap Nominatim."""
    try:
        resp = await request.app.state.http.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": 5},
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Geocoding failed: {exc}") from exc
    return [
        {"name": r.get("display_name"), "latitude": float(r["lat"]), "longitude": float(r["lon"])}
        for r in resp.json()
    ]


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
