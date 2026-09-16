"""
Traffic Monitor add-on entrypoint.

M3 scope: multi-route config. Routes are persisted in /data/routes.json
(routes_store.py) and managed via the /api/routes CRUD API (api.py) and
RouteManager (manager.py), which keeps one poll task per enabled route in
sync with the store and publishes/clears MQTT discovery as routes are
added, changed, or removed. The map UI and route pinning land in M4/M5 --
see ROADMAP.md.
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

from app.api import router as api_router
from app.budget import BudgetGuard
from app.geocache import CachedGeocoder, GeocodeCache
from app.manager import RouteManager
from app.models import Route
from app.mqtt import MqttConfig, MqttPublisher
from app.providers.tomtom import TomTomConfig, TomTomProvider
from app.routes_store import RoutesStore, new_route_id

logger = logging.getLogger("traffic_monitor")

APP_DIR = Path(__file__).resolve().parent
WWW_DIR = APP_DIR.parent / "www"
DATA_DIR = Path(os.environ.get("TM_DATA_DIR", "/data"))


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


def _seed_legacy_route(store: RoutesStore) -> None:
    """One-time migration: M2 stored a single route directly in add-on
    options (route_origin/route_destination/...). If routes.json is empty
    and those options are still set, carry that route forward so
    upgrading doesn't silently drop it. Only runs while the store is
    empty -- once any route exists (including this seeded one), it's a
    no-op on every subsequent boot."""
    if store.list():
        return
    origin = os.environ.get("TM_ROUTE_ORIGIN", "")
    destination = os.environ.get("TM_ROUTE_DESTINATION", "")
    if not origin or not destination:
        return
    name = os.environ.get("TM_ROUTE_NAME", "My Commute")
    logger.info("Migrating legacy single-route config (%r) into routes.json", name)
    store.create(
        Route(
            id=new_route_id(name),
            name=name,
            origin_address=origin,
            destination_address=destination,
            avoid_tolls=_bool_env("TM_ROUTE_AVOID_TOLLS"),
            poll_interval_minutes=int(os.environ.get("TM_ROUTE_POLL_INTERVAL_MINUTES", "15") or 15),
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    for attr in ("provider", "geocoder", "budget", "mqtt", "store", "manager"):
        setattr(app.state, attr, None)

    tasks: list[asyncio.Task] = []
    stop_event = asyncio.Event()
    provider: TomTomProvider | None = None

    api_key = os.environ.get("TM_API_KEY", "")
    mqtt_host = os.environ.get("TM_MQTT_HOST", "")

    if not api_key:
        logger.warning("No TomTom API key configured -- the API will accept no routes until one is set.")
    else:
        provider = TomTomProvider(TomTomConfig(api_key=api_key))
        geocoder = CachedGeocoder(provider, GeocodeCache(DATA_DIR / "geocache.json"))
        budget = BudgetGuard(path=DATA_DIR / "usage.json")
        app.state.provider = provider
        app.state.geocoder = geocoder
        app.state.budget = budget

        store = RoutesStore(DATA_DIR / "routes.json")
        _seed_legacy_route(store)
        app.state.store = store

        if not mqtt_host:
            logger.warning(
                "No MQTT broker detected -- routes can be managed via the API but won't be "
                "polled or published until MQTT is set up."
            )
        else:
            mqtt = MqttPublisher(
                MqttConfig(
                    host=mqtt_host,
                    port=int(os.environ.get("TM_MQTT_PORT") or 1883),
                    username=os.environ.get("TM_MQTT_USERNAME") or None,
                    password=os.environ.get("TM_MQTT_PASSWORD") or None,
                ),
                unit_system=os.environ.get("TM_UNIT_SYSTEM", "metric"),
            )
            manager = RouteManager(provider, geocoder, budget, mqtt, store)
            app.state.mqtt = mqtt
            app.state.manager = manager

            tasks.append(asyncio.create_task(mqtt.run(stop_event, on_connect=manager.on_mqtt_connect), name="mqtt"))
            await manager.start_all()
            logger.info("Managing %d route(s)", len(store.list()))

    try:
        yield
    finally:
        stop_event.set()
        manager: RouteManager | None = getattr(app.state, "manager", None)
        if manager is not None:
            await manager.shutdown()
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
app.include_router(api_router)


@app.get("/api/status")
def status() -> dict:
    """Liveness/config-sanity endpoint backing the UI's status banner."""
    # getattr, not app.state.budget: the status endpoint should never 500,
    # including if it's ever hit before/without the lifespan having run
    # (e.g. a bare TestClient() in a test, with no context manager).
    budget: BudgetGuard | None = getattr(app.state, "budget", None)
    mqtt: MqttPublisher | None = getattr(app.state, "mqtt", None)
    store: RoutesStore | None = getattr(app.state, "store", None)
    return {
        "status": "ok",
        "version": "0.4.0",
        "api_key_configured": bool(os.environ.get("TM_API_KEY")),
        "unit_system": os.environ.get("TM_UNIT_SYSTEM", "metric"),
        "mqtt_configured": bool(os.environ.get("TM_MQTT_HOST")),
        "mqtt_connected": mqtt.connected if mqtt else False,
        "route_count": len(store.list()) if store else 0,
        "api_requests_used_30d": budget.used() if budget else None,
        "api_requests_remaining": budget.remaining() if budget else None,
    }


# Serve the (currently placeholder) ingress UI as static files.
if WWW_DIR.exists():
    app.mount("/static", StaticFiles(directory=WWW_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WWW_DIR / "index.html")
