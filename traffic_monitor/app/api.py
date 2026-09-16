"""
/api/routes CRUD, /api/routes/preview, and /api/usage (ROADMAP.md M3).

Handlers go through RouteManager (app.state.manager) rather than
RoutesStore directly, so every write gets its side effects: starting/
stopping the route's poll task and publishing or clearing its MQTT
discovery configs. Reads that don't need those side effects (list/get)
go straight to the store.

Everything here reads its dependencies off `request.app.state`, set up by
main.py's lifespan -- when the add-on isn't configured yet (no API key),
those attributes are None and routes here return 503 rather than crashing.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models import Route, RouteCalculation, Schedule
from app.providers.base import ProviderError
from app.routes_store import new_route_id

router = APIRouter(prefix="/api")


class RouteWrite(BaseModel):
    """Shared shape for create and update -- a route minus its id (POST
    generates one; PUT takes it from the path)."""

    name: str
    origin_address: str
    destination_address: str
    avoid_tolls: bool = False
    poll_interval_minutes: int = Field(15, ge=1, le=1440)
    schedule: Schedule = Field(default_factory=Schedule)
    enabled: bool = True


class PreviewRequest(BaseModel):
    origin_address: str
    destination_address: str
    avoid_tolls: bool = False


def _require_manager(request: Request):
    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(503, "Not configured yet -- set an API key and MQTT broker first")
    return manager


def _require_store(request: Request):
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(503, "Not configured yet -- set an API key first")
    return store


@router.get("/routes", response_model=list[Route])
def list_routes(request: Request) -> list[Route]:
    return _require_store(request).list()


@router.post("/routes", response_model=Route, status_code=201)
async def create_route(body: RouteWrite, request: Request) -> Route:
    manager = _require_manager(request)
    route = Route(id=new_route_id(body.name), **body.model_dump())
    try:
        return await manager.create_route(route)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/routes/{route_id}", response_model=Route)
def get_route(route_id: str, request: Request) -> Route:
    route = _require_store(request).get(route_id)
    if route is None:
        raise HTTPException(404, f"No route {route_id!r}")
    return route


@router.put("/routes/{route_id}", response_model=Route)
async def update_route(route_id: str, body: RouteWrite, request: Request) -> Route:
    manager = _require_manager(request)
    if _require_store(request).get(route_id) is None:
        raise HTTPException(404, f"No route {route_id!r}")
    route = Route(id=route_id, **body.model_dump())
    return await manager.update_route(route_id, route)


@router.delete("/routes/{route_id}", status_code=204, response_model=None)
async def delete_route(route_id: str, request: Request) -> None:
    manager = _require_manager(request)
    removed = await manager.delete_route(route_id)
    if removed is None:
        raise HTTPException(404, f"No route {route_id!r}")


@router.post("/routes/preview", response_model=RouteCalculation)
async def preview_route(body: PreviewRequest, request: Request) -> RouteCalculation:
    """Geocodes + calculates a route with alternatives and full geometry
    WITHOUT saving it -- lets a future map UI (M4) show alternatives
    before the user commits to one. Spends real API budget, same as a
    saved route's poll, so it's guarded by the same budget check."""
    provider = getattr(request.app.state, "provider", None)
    geocoder = getattr(request.app.state, "geocoder", None)
    budget = getattr(request.app.state, "budget", None)
    if provider is None or geocoder is None or budget is None:
        raise HTTPException(503, "Not configured yet -- set an API key first")
    if not budget.allow():
        raise HTTPException(429, "Monthly API budget exhausted")

    try:
        origin = await geocoder.geocode(body.origin_address)
        destination = await geocoder.geocode(body.destination_address)
        calc = await provider.calculate_route(
            origin.point,
            destination.point,
            avoid_tolls=body.avoid_tolls,
            max_alternatives=5,
            include_geometry=True,
        )
        budget.record()
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return calc


@router.get("/usage")
def usage(request: Request) -> dict:
    budget = getattr(request.app.state, "budget", None)
    if budget is None:
        raise HTTPException(503, "Not configured yet -- set an API key first")
    return {
        "used_30d": budget.used(),
        "remaining": budget.remaining(),
        "monthly_limit": budget.monthly_limit,
        "usage_ratio": budget.usage_ratio(),
        "warning": budget.is_warning(),
        "exhausted": budget.is_exhausted(),
    }
