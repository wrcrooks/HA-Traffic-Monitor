"""
Traffic Monitor add-on entrypoint.

M0 scope: prove the add-on installs, starts under Home Assistant's Supervisor,
and serves a page through ingress. Routing, MQTT, and scheduling land in
later milestones (see ROADMAP.md) and will be wired in here as they're built.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("traffic_monitor")

APP_DIR = Path(__file__).resolve().parent
WWW_DIR = APP_DIR.parent / "www"

app = FastAPI(title="Traffic Monitor")


@app.get("/api/status")
def status() -> dict:
    """Minimal liveness/config-sanity endpoint, useful for the M0 smoke test
    and later as the basis for the UI's status banner."""
    api_key = os.environ.get("TM_API_KEY", "")
    return {
        "status": "ok",
        "version": "0.1.0",
        "api_key_configured": bool(api_key),
        "unit_system": os.environ.get("TM_UNIT_SYSTEM", "metric"),
        "mqtt_configured": bool(os.environ.get("TM_MQTT_HOST")),
    }


# Serve the (currently placeholder) ingress UI as static files.
if WWW_DIR.exists():
    app.mount("/static", StaticFiles(directory=WWW_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WWW_DIR / "index.html")
