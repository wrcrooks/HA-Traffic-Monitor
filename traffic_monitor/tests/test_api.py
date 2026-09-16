"""
Tests the /api/routes CRUD, /api/routes/preview, and /api/usage endpoints
through a real TestClient(app), against fake provider/geocoder/mqtt and a
real RoutesStore/BudgetGuard backed by tmp_path.

Important: manager mutations happen ONLY through client.*() HTTP calls
here, never by directly awaiting manager methods in the test coroutine.
TestClient runs the ASGI app (and anything it awaits, including the
asyncio tasks RouteManager creates) on its own event loop via a blocking
portal, separate from pytest-asyncio's loop for the test function itself
-- awaiting manager methods directly from the test would create
loop-bound objects (asyncio.Task/Event) on the wrong loop. Going through
HTTP calls keeps everything on the portal's loop consistently, and
TestClient blocks until each call fully completes, so reading fake state
(discovery_calls, etc.) right after a call is race-free.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.budget import BudgetGuard
from app.main import app
from app.manager import RouteManager
from app.models import GeocodeResult, GeoPoint, RouteAlternative, RouteCalculation, RouteSummary
from app.routes_store import RoutesStore


class _FakeProvider:
    async def calculate_route(self, origin, destination, **kwargs):
        return RouteCalculation(
            routes=[
                RouteAlternative(
                    index=0,
                    summary=RouteSummary(
                        duration_seconds=1000,
                        duration_typical_seconds=900,
                        incident_delay_seconds=0,
                        length_meters=10000,
                    ),
                )
            ],
            queried_at=datetime.now().astimezone(),
        )


class _FakeGeocoder:
    async def geocode(self, address):
        return GeocodeResult(query=address, point=GeoPoint(lat=1, lon=2), formatted_address=address)


class _FakeMqtt:
    def __init__(self) -> None:
        self.discovery_calls: list[list[str]] = []
        self.cleared: list[str] = []
        self._last_state: dict[str, dict] = {}

    async def publish_discovery(self, routes) -> None:
        self.discovery_calls.append([r.id for r in routes])

    async def clear_route(self, route) -> None:
        self.cleared.append(route.id)
        self._last_state.pop(route.id, None)

    def last_state(self, route_id: str) -> dict | None:
        return self._last_state.get(route_id)

    def all_last_state(self) -> dict:
        return dict(self._last_state)

    def set_status(self, route_id: str, payload: dict) -> None:
        """Test helper -- simulates a poll having happened."""
        self._last_state[route_id] = payload


async def _noop_poll_fn(provider, geocoder, budget, mqtt, route, stop_event) -> None:
    await stop_event.wait()


@pytest.fixture
def configured_client(tmp_path):
    with TestClient(app) as c:
        # Overwrite the (None, "not configured") state the real lifespan
        # set up, since no env vars are present in the test environment.
        app.state.store = RoutesStore(tmp_path / "routes.json")
        app.state.provider = _FakeProvider()
        app.state.geocoder = _FakeGeocoder()
        app.state.budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
        app.state.mqtt = _FakeMqtt()
        app.state.manager = RouteManager(
            app.state.provider,
            app.state.geocoder,
            app.state.budget,
            app.state.mqtt,
            app.state.store,
            poll_fn=_noop_poll_fn,
        )
        yield c
    # lifespan shutdown (on `with` exit) awaits app.state.manager.shutdown(),
    # cleaning up any tasks started during the test.


@pytest.fixture
def unconfigured_client():
    with TestClient(app) as c:
        yield c


# -- CRUD --------------------------------------------------------------------


def test_list_routes_starts_empty(configured_client):
    resp = configured_client.get("/api/routes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_route_returns_201_with_generated_id(configured_client):
    resp = configured_client.post(
        "/api/routes",
        json={"name": "Commute", "origin_address": "A", "destination_address": "B", "avoid_tolls": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("commute_")
    assert body["avoid_tolls"] is True
    assert body["enabled"] is True


def test_created_route_appears_in_list_and_publishes_discovery(configured_client):
    resp = configured_client.post(
        "/api/routes", json={"name": "Commute", "origin_address": "A", "destination_address": "B"}
    )
    route_id = resp.json()["id"]

    listed = configured_client.get("/api/routes").json()
    assert [r["id"] for r in listed] == [route_id]
    assert app.state.mqtt.discovery_calls == [[route_id]]


def test_get_route_404_for_missing(configured_client):
    resp = configured_client.get("/api/routes/nope")
    assert resp.status_code == 404


def test_get_route_returns_it(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()
    resp = configured_client.get(f"/api/routes/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "R"


def test_update_route_replaces_fields(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "Old", "origin_address": "A", "destination_address": "B"}
    ).json()
    resp = configured_client.put(
        f"/api/routes/{created['id']}",
        json={
            "name": "New",
            "origin_address": "A2",
            "destination_address": "B2",
            "avoid_tolls": True,
            "poll_interval_minutes": 30,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]  # id preserved from the path, not regenerated
    assert body["name"] == "New"
    assert body["avoid_tolls"] is True
    assert body["poll_interval_minutes"] == 30


def test_update_route_404_for_missing(configured_client):
    resp = configured_client.put(
        "/api/routes/nope", json={"name": "X", "origin_address": "A", "destination_address": "B"}
    )
    assert resp.status_code == 404


def test_delete_route_then_404_on_subsequent_get(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()

    resp = configured_client.delete(f"/api/routes/{created['id']}")
    assert resp.status_code == 204
    assert app.state.mqtt.cleared == [created["id"]]

    assert configured_client.get(f"/api/routes/{created['id']}").status_code == 404


def test_delete_route_404_for_missing(configured_client):
    resp = configured_client.delete("/api/routes/nope")
    assert resp.status_code == 404


def test_create_route_invalid_poll_interval_rejected(configured_client):
    resp = configured_client.post(
        "/api/routes",
        json={
            "name": "R",
            "origin_address": "A",
            "destination_address": "B",
            "poll_interval_minutes": 0,  # below the ge=1 constraint
        },
    )
    assert resp.status_code == 422


def test_create_route_with_selected_alternative_points_roundtrips(configured_client):
    points = [{"lat": 30.1, "lon": -95.6}, {"lat": 30.2, "lon": -95.5}]
    created = configured_client.post(
        "/api/routes",
        json={
            "name": "Pinned",
            "origin_address": "A",
            "destination_address": "B",
            "selected_alternative_points": points,
        },
    ).json()
    assert created["selected_alternative_points"] == points

    fetched = configured_client.get(f"/api/routes/{created['id']}").json()
    assert fetched["selected_alternative_points"] == points


def test_create_route_without_selected_alternative_points_is_null(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()
    assert created["selected_alternative_points"] is None


# -- status --------------------------------------------------------------


def test_all_route_status_empty_before_any_poll(configured_client):
    configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    )
    resp = configured_client.get("/api/routes/status")
    assert resp.status_code == 200
    assert resp.json() == {}  # created, but the (noop) poller hasn't published anything


def test_all_route_status_reflects_mqtt_cache(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()
    app.state.mqtt.set_status(created["id"], {"duration_minutes": 12.3, "stale": False})

    resp = configured_client.get("/api/routes/status")
    assert resp.json() == {created["id"]: {"duration_minutes": 12.3, "stale": False}}


def test_single_route_status_404_for_missing_route(configured_client):
    resp = configured_client.get("/api/routes/nope/status")
    assert resp.status_code == 404


def test_single_route_status_null_before_first_poll(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()
    resp = configured_client.get(f"/api/routes/{created['id']}/status")
    assert resp.status_code == 200
    assert resp.json() is None


def test_single_route_status_reflects_mqtt_cache(configured_client):
    created = configured_client.post(
        "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
    ).json()
    app.state.mqtt.set_status(created["id"], {"duration_minutes": 42.0})

    resp = configured_client.get(f"/api/routes/{created['id']}/status")
    assert resp.json() == {"duration_minutes": 42.0}


def test_all_route_status_empty_dict_when_not_configured(unconfigured_client):
    # Deliberately not a 503 -- an empty status map is a valid, harmless
    # answer even before MQTT exists, unlike the other endpoints.
    resp = unconfigured_client.get("/api/routes/status")
    assert resp.status_code == 200
    assert resp.json() == {}


# -- preview / usage -----------------------------------------------------


def test_preview_route_returns_calculation(configured_client):
    resp = configured_client.post(
        "/api/routes/preview", json={"origin_address": "A", "destination_address": "B"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["routes"]) == 1
    assert body["routes"][0]["summary"]["duration_seconds"] == 1000


def test_preview_route_records_budget_usage(configured_client):
    configured_client.post("/api/routes/preview", json={"origin_address": "A", "destination_address": "B"})
    usage = configured_client.get("/api/usage").json()
    assert usage["used_30d"] == 1


def test_usage_endpoint_reports_budget_figures(configured_client):
    resp = configured_client.get("/api/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "used_30d": 0,
        "remaining": 100,
        "monthly_limit": 100,
        "usage_ratio": 0.0,
        "warning": False,
        "exhausted": False,
    }


# -- not configured yet (no API key) -----------------------------------


def test_routes_endpoints_503_when_not_configured(unconfigured_client):
    assert unconfigured_client.get("/api/routes").status_code == 503
    assert (
        unconfigured_client.post(
            "/api/routes", json={"name": "R", "origin_address": "A", "destination_address": "B"}
        ).status_code
        == 503
    )


def test_preview_503_when_not_configured(unconfigured_client):
    resp = unconfigured_client.post(
        "/api/routes/preview", json={"origin_address": "A", "destination_address": "B"}
    )
    assert resp.status_code == 503


def test_usage_503_when_not_configured(unconfigured_client):
    assert unconfigured_client.get("/api/usage").status_code == 503
