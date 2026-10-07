"""FastAPI layer: a JSON API for other programs, plus the web page for people."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from .checker import check_website
from .database import (
    add_to_watchlist,
    get_history,
    get_watchlist,
    init_db,
    is_watched,
    remove_from_watchlist,
    save_checks,
)
from .diagnose import diagnose
from .ratelimit import is_allowed
from .safety import TargetNotAllowed, validate_target
from .stats import get_uptime_stats
from .worker import CHECK_INTERVAL_SECONDS, start_worker, stop_worker

STATIC_DIR = Path(__file__).resolve().parent / "static"
HISTORY_LIMIT = 30
MAX_WATCHLIST = 50
# Set MONITOR_WORKER=0 to run the API without the background checker
WORKER_ENABLED = os.environ.get("MONITOR_WORKER", "1") == "1"
API_KEY = os.environ.get("API_KEY", "")


@asynccontextmanager
async def lifespan(app):
    init_db()  # make sure the tables exist when the server starts
    if WORKER_ENABLED:
        start_worker()  # resumes checking everything already in the watchlist
    yield
    stop_worker()


app = FastAPI(
    title="Uptime Monitor API",
    description="Check whether a domain or IP address is up, see its uptime history "
                "and keep it under automatic monitoring.",
    version="1.2.0",
    lifespan=lifespan,
)


# ---------- rate limiting (applies to every /api/ call) ----------

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if not is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and try again shortly."},
            )
    return await call_next(request)


# ---------- API key ----------

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str = Depends(api_key_header)):
    """Block the request unless it carries the correct X-API-Key header.

    If no API_KEY is configured in .env, the API stays open (useful for local
    development). Set API_KEY before sharing this server with anyone else.
    """
    if not API_KEY:
        return
    if key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key. Send it in the X-API-Key header.",
        )


class WatchRequest(BaseModel):
    target: str = Field(..., min_length=1, max_length=300, examples=["google.com"])


# ---------- helpers ----------

def _validate(target):
    """Turn a safety failure into a proper HTTP error."""
    try:
        validate_target(target)
    except TargetNotAllowed as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _find_saved(target):
    """Match what the user typed to a saved target (google.com or https://google.com)."""
    for candidate in (target, "https://" + target, "http://" + target):
        if get_history(candidate, 1):
            return candidate
    return None


def _current(latest):
    return {
        "is_up": bool(latest["is_up"]),
        "status_code": latest["status_code"],
        "response_time_ms": latest["response_time_ms"],
        "error": latest["error"],
        "checked_at": latest["checked_at"],
        "checked_url": latest["checked_url"],
        "target_type": latest["target_type"],
        "resolved_ip": latest["resolved_ip"],
    }


def _history_item(row):
    return {
        "checked_at": row["checked_at"],
        "is_up": bool(row["is_up"]),
        "status_code": row["status_code"],
        "response_time_ms": row["response_time_ms"],
        "error": row["error"],
    }


def build_report(target, latest=None):
    """Combine the latest check, uptime statistics and recent history."""
    rows = get_history(target, HISTORY_LIMIT)
    stats = get_uptime_stats(target)
    if latest is None:
        latest = rows[0]

    avg = stats["avg_response_ms"]
    return {
        "target": target,
        "monitored": is_watched(target),
        "interval_seconds": CHECK_INTERVAL_SECONDS,
        "current": _current(latest),
        "diagnosis": diagnose(dict(latest)),
        "stats": {
            "uptime_percent": round(stats["uptime_percent"], 2),
            "total_checks": stats["total"],
            "successful": stats["successful"],
            "failed": stats["failed"],
            "avg_response_ms": round(avg) if avg is not None else None,
        },
        "history": [_history_item(row) for row in rows],  # newest first
    }


# ---------- endpoints ----------

@app.get("/", include_in_schema=False)
def home():
    """Serve the web page. The API key is embedded so the browser UI can use it."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__API_KEY__", API_KEY)
    return HTMLResponse(html)


@app.get("/api/health", summary="Is the API running?")
def health():
    return {"status": "ok", "worker": WORKER_ENABLED, "auth_required": bool(API_KEY)}


@app.get("/api/check", summary="Check a domain or IP now and return its report",
          dependencies=[Depends(require_api_key)])
def check(
    target: str = Query(
        ..., min_length=1, max_length=300,
        description="Domain, IP address or URL, e.g. google.com or 8.8.8.8",
    ),
):
    target = target.strip()
    _validate(target)

    result = check_website(target)
    save_checks([result])
    return build_report(target, result)


@app.get("/api/report", summary="Uptime statistics and history (no new check)",
          dependencies=[Depends(require_api_key)])
def report(
    target: str = Query(..., min_length=1, max_length=300),
):
    saved = _find_saved(target.strip())
    if saved is None:
        raise HTTPException(
            status_code=404,
            detail="No records for this target yet. Call /api/check first.",
        )
    return build_report(saved)


@app.get("/api/watchlist", summary="List all monitored targets",
          dependencies=[Depends(require_api_key)])
def watchlist():
    return {"interval_seconds": CHECK_INTERVAL_SECONDS, "targets": get_watchlist()}


@app.post("/api/watchlist", summary="Start monitoring a target automatically",
           dependencies=[Depends(require_api_key)])
def watch(body: WatchRequest):
    target = body.target.strip()
    _validate(target)

    if not is_watched(target) and len(get_watchlist()) >= MAX_WATCHLIST:
        raise HTTPException(
            status_code=409,
            detail=f"The watchlist is full ({MAX_WATCHLIST} targets). Remove one first.",
        )

    added = add_to_watchlist(target)
    return {
        "target": target,
        "monitored": True,
        "already_monitored": not added,
        "interval_seconds": CHECK_INTERVAL_SECONDS,
    }


@app.delete("/api/watchlist", summary="Stop monitoring a target (history is kept)",
             dependencies=[Depends(require_api_key)])
def unwatch(
    target: str = Query(..., min_length=1, max_length=300),
):
    target = target.strip()
    removed = remove_from_watchlist(target)
    return {"target": target, "monitored": False, "removed": removed} 