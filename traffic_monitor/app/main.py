"""
Traffic Monitor add-on entrypoint.

M2 scope: a walking skeleton. One hardcoded route (from add-on options) is
geocoded, polled on a fixed interval against TomTom, and published to MQTT
as a real HA device with discovery configs. Multi-route config, the map
UI, and route pinning land in M3-M5 (see ROADMAP.md).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Note: the Windows event-loop-policy fix needed for local dev testing
# (aiomqtt needs add_reader/add_writer, which Windows' default
# ProactorEventLoop doesn't implement) lives in __main__.py, not here --
# by the time this module is imported under `python -m uvicorn
# app.main:app`, uvicorn has already created its event loop, so setting
# the policy at this point has no effect. See __main__.py.

from app.budget import BudgetGuard
from app.geocache import CachedGeocoder, GeocodeCache
from app.models import RouteConfig
from app.mqtt import MqttConfig, MqttPublisher
from app.providers.tomtom import TomTomConfig, TomTomProvider
from app.scheduler import poll_forever

logger = logging.getLogger("traffic_monitor")

APP_DIR = Path(__file__).resolve().parent
WWW_DIR = APP_DIR.parent / "www"
DATA_DIR = Path(os.environ.get("TM_DATA_DIR", "/data"))


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.budget = None
    app.state.mqtt = None

    tasks: list[asyncio.Task] = []
    stop_event = asyncio.Event()
    provider: TomTomProvider | None = None

    api_key = os.environ.get("TM_API_KEY", "")
    mqtt_host = os.environ.get("TM_MQTT_HOST", "")
    route_origin = os.environ.get("TM_ROUTE_ORIGIN", "")
    route_destination = os.environ.get("TM_ROUTE_DESTINATION", "")

    if not api_key:
        logger.warning("No TomTom API key configured -- polling will not start.")
    elif not mqtt_host:
        logger.warning("No MQTT broker detected -- entities will not be published until MQTT is set up.")
    elif not route_origin or not route_destination:
        logger.warning("No route configured yet -- set route_origin/route_destination and restart.")
    else:
        provider = TomTomProvider(TomTomConfig(api_key=api_key))
        geocoder = CachedGeocoder(provider, GeocodeCache(DATA_DIR / "geocache.json"))
        budget = BudgetGuard(path=DATA_DIR / "usage.json")
        mqtt = MqttPublisher(
            MqttConfig(
                host=mqtt_host,
                port=int(os.environ.get("TM_MQTT_PORT") or 1883),
                username=os.environ.get("TM_MQTT_USERNAME") or None,
                password=os.environ.get("TM_MQTT_PASSWORD") or None,
            ),
            unit_system=os.environ.get("TM_UNIT_SYSTEM", "metric"),
        )
        route = RouteConfig(
            route_id="commute",
            name=os.environ.get("TM_ROUTE_NAME", "My Commute"),
            origin_address=route_origin,
            destination_address=route_destination,
            avoid_tolls=_bool_env("TM_ROUTE_AVOID_TOLLS"),
        )
        interval_seconds = float(os.environ.get("TM_ROUTE_POLL_INTERVAL_MINUTES", "15")) * 60

        app.state.budget = budget
        app.state.mqtt = mqtt

        tasks.append(asyncio.create_task(mqtt.run([route], stop_event), name="mqtt"))
        tasks.append(
            asyncio.create_task(
                poll_forever(provider, geocoder, budget, mqtt, route, interval_seconds, stop_event),
                name="poll",
            )
        )
        logger.info("Started polling %r every %.0f minutes", route.name, interval_seconds / 60)

    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if provider is not None:
            await provider.aclose()


app = FastAPI(title="Traffic Monitor", lifespan=lifespan)


@app.get("/api/status")
def status() -> dict:
    """Liveness/config-sanity endpoint backing the UI's status banner."""
    # getattr, not app.state.budget: the status endpoint should never 500,
    # including if it's ever hit before/without the lifespan having run
    # (e.g. a bare TestClient() in a test, with no context manager).
    budget: BudgetGuard | None = getattr(app.state, "budget", None)
    mqtt: MqttPublisher | None = getattr(app.state, "mqtt", None)
    return {
        "status": "ok",
        "version": "0.2.0",
        "api_key_configured": bool(os.environ.get("TM_API_KEY")),
        "unit_system": os.environ.get("TM_UNIT_SYSTEM", "metric"),
        "mqtt_configured": bool(os.environ.get("TM_MQTT_HOST")),
        "mqtt_connected": mqtt.connected if mqtt else False,
        "route_configured": bool(
            os.environ.get("TM_ROUTE_ORIGIN") and os.environ.get("TM_ROUTE_DESTINATION")
        ),
        "api_requests_used_30d": budget.used() if budget else None,
        "api_requests_remaining": budget.remaining() if budget else None,
    }


# Serve the (currently placeholder) ingress UI as static files.
if WWW_DIR.exists():
    app.mount("/static", StaticFiles(directory=WWW_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WWW_DIR / "index.html")
