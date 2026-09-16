"""
Offline tests for TomTomProvider, run entirely against recorded fixtures
(tests/fixtures/) via respx -- no network access, no API quota spent.

Most fixtures are real responses captured during M1 development against
the user's actual commute (Magnolia, TX -> Spring, TX); rate_limited.json
is the one synthetic exception (see its _fixture_note).
"""
from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from app.models import GeoPoint
from app.providers.base import (
    AuthenticationError,
    GeocodeNotFoundError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.providers.tomtom import TomTomConfig, TomTomProvider
from tests.conftest import load_fixture

GEOCODE_RE = re.compile(r"https://api\.tomtom\.com/search/2/geocode/.*")
ROUTE_RE = re.compile(r"https://api\.tomtom\.com/routing/1/calculateRoute/.*")

ORIGIN = GeoPoint(lat=30.1189912, lon=-95.6744238)
DESTINATION = GeoPoint(lat=30.1025496, lon=-95.4463921)


def _config(**overrides) -> TomTomConfig:
    defaults = {"api_key": "test-key", "max_retries": 1}
    defaults.update(overrides)
    return TomTomConfig(**defaults)


# -- geocoding -----------------------------------------------------------


@respx.mock
async def test_geocode_success():
    respx.get(GEOCODE_RE).mock(return_value=httpx.Response(200, json=load_fixture("geocode_origin.json")))
    async with TomTomProvider(_config()) as provider:
        result = await provider.geocode("Decker Farms, Magnolia, TX 77355")
    assert result.point.lat == pytest.approx(30.1189912)
    assert result.point.lon == pytest.approx(-95.6744238)
    assert "Decker Farms" in result.formatted_address


@respx.mock
async def test_geocode_not_found_raises():
    respx.get(GEOCODE_RE).mock(
        return_value=httpx.Response(200, json=load_fixture("geocode_not_found.json"))
    )
    async with TomTomProvider(_config()) as provider:
        with pytest.raises(GeocodeNotFoundError):
            await provider.geocode("zzqxnonexistentplace123456")


# -- error handling --------------------------------------------------------


@respx.mock
async def test_auth_error_raises_without_retrying():
    route = respx.get(GEOCODE_RE).mock(
        return_value=httpx.Response(401, json=load_fixture("auth_error.json"))
    )
    async with TomTomProvider(_config(max_retries=3)) as provider:
        with pytest.raises(AuthenticationError):
            await provider.geocode("test")
    # Auth failures are not transient -- retrying a bad key wastes budget
    # for no benefit.
    assert route.call_count == 1


@respx.mock
async def test_rate_limited_raises():
    respx.get(GEOCODE_RE).mock(
        return_value=httpx.Response(429, json=load_fixture("rate_limited.json"))
    )
    async with TomTomProvider(_config(max_retries=0)) as provider:
        with pytest.raises(RateLimitedError):
            await provider.geocode("test")


@respx.mock
async def test_timeout_retries_then_succeeds():
    route = respx.get(GEOCODE_RE)
    route.side_effect = [
        httpx.TimeoutException("simulated timeout"),
        httpx.Response(200, json=load_fixture("geocode_origin.json")),
    ]
    async with TomTomProvider(_config(max_retries=2)) as provider:
        result = await provider.geocode("Decker Farms, Magnolia, TX 77355")
    assert result.point.lat == pytest.approx(30.1189912)
    assert route.call_count == 2


@respx.mock
async def test_exhausted_retries_raise_provider_unavailable():
    respx.get(GEOCODE_RE).mock(return_value=httpx.Response(500, json={"detailedError": {}}))
    async with TomTomProvider(_config(max_retries=1)) as provider:
        with pytest.raises(ProviderUnavailableError):
            await provider.geocode("test")


# -- routing ---------------------------------------------------------------


@respx.mock
async def test_calculate_route_returns_alternatives_with_geometry():
    respx.get(ROUTE_RE).mock(return_value=httpx.Response(200, json=load_fixture("route_with_tolls.json")))
    async with TomTomProvider(_config()) as provider:
        calc = await provider.calculate_route(
            ORIGIN, DESTINATION, max_alternatives=2, include_geometry=True
        )
    assert len(calc.routes) >= 2
    fastest = calc.routes[0]
    assert fastest.summary.duration_seconds > 0
    assert fastest.summary.length_meters > 0
    assert len(fastest.points) > 0


@respx.mock
async def test_calculate_route_avoid_tolls_sets_param():
    route = respx.get(ROUTE_RE).mock(
        return_value=httpx.Response(200, json=load_fixture("route_without_tolls.json"))
    )
    async with TomTomProvider(_config()) as provider:
        await provider.calculate_route(ORIGIN, DESTINATION, avoid_tolls=True)
    assert route.calls.last.request.url.params["avoid"] == "tollRoads"


@respx.mock
async def test_calculate_route_without_avoid_tolls_omits_param():
    route = respx.get(ROUTE_RE).mock(
        return_value=httpx.Response(200, json=load_fixture("route_with_tolls.json"))
    )
    async with TomTomProvider(_config()) as provider:
        await provider.calculate_route(ORIGIN, DESTINATION, avoid_tolls=False)
    assert "avoid" not in route.calls.last.request.url.params


@respx.mock
async def test_calculate_route_reconstruction_uses_post_with_plain_point_array():
    """Regression test for the schema mistake caught during M1: TomTom
    rejects supportingPoints as GeoJSON (INVALID_REQUEST) -- it must be a
    plain array of {latitude, longitude} objects."""
    route = respx.post(ROUTE_RE).mock(
        return_value=httpx.Response(200, json=load_fixture("route_reconstruction.json"))
    )
    supporting = [GeoPoint(lat=30.119, lon=-95.674), GeoPoint(lat=30.09, lon=-95.5)]
    async with TomTomProvider(_config()) as provider:
        calc = await provider.calculate_route(
            ORIGIN, DESTINATION, supporting_points=supporting, include_geometry=True
        )
    assert len(calc.routes) == 1
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["supportingPoints"] == [
        {"latitude": 30.119, "longitude": -95.674},
        {"latitude": 30.09, "longitude": -95.5},
    ]
    # A reconstruction request has exactly one route -- maxAlternatives
    # is meaningless for "recompute this specific path."
    assert "maxAlternatives" not in route.calls.last.request.url.params
