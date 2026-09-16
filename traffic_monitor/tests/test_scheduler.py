from __future__ import annotations

import asyncio

import pytest

from app.budget import BudgetGuard
from app.models import GeocodeResult, GeoPoint, RouteAlternative, RouteCalculation, RouteConfig, RouteSummary
from app.providers.base import ProviderError
from app.scheduler import _poll_once, poll_forever

ROUTE = RouteConfig(
    route_id="commute",
    name="My Commute",
    origin_address="origin address",
    destination_address="destination address",
    avoid_tolls=False,
)

SUMMARY = RouteSummary(
    duration_seconds=1702, duration_typical_seconds=1535, incident_delay_seconds=0, length_meters=33370
)


class _FakeProvider:
    def __init__(self, calc: RouteCalculation | None = None, error: Exception | None = None) -> None:
        self._calc = calc
        self._error = error
        self.calls = 0

    async def calculate_route(self, *args, **kwargs) -> RouteCalculation:
        self.calls += 1
        if self._error:
            raise self._error
        return self._calc


class _FakeGeocoder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def geocode(self, address: str) -> GeocodeResult:
        if self.fail:
            raise ProviderError("no results")
        return GeocodeResult(query=address, point=GeoPoint(lat=1.0, lon=2.0), formatted_address=address)


class _FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[RouteConfig, RouteAlternative]] = []

    async def publish_state(self, route: RouteConfig, alternative: RouteAlternative) -> None:
        self.published.append((route, alternative))


def _calc_with_one_route() -> RouteCalculation:
    from datetime import datetime

    return RouteCalculation(
        routes=[RouteAlternative(index=0, summary=SUMMARY)], queried_at=datetime.now().astimezone()
    )


# -- _poll_once ----------------------------------------------------------


async def test_poll_once_publishes_and_records_budget(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    mqtt = _FakeMqtt()

    await _poll_once(provider, budget, mqtt, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert provider.calls == 1
    assert budget.used() == 1
    assert len(mqtt.published) == 1
    assert mqtt.published[0][0] == ROUTE


async def test_poll_once_skips_when_budget_exhausted(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=1)
    budget.record(1)  # already exhausted
    mqtt = _FakeMqtt()

    await _poll_once(provider, budget, mqtt, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert provider.calls == 0  # never even called the provider
    assert len(mqtt.published) == 0


async def test_poll_once_swallows_provider_errors(tmp_path):
    provider = _FakeProvider(error=ProviderError("boom"))
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    mqtt = _FakeMqtt()

    # Must not raise -- a single bad poll should not kill the loop.
    await _poll_once(provider, budget, mqtt, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert len(mqtt.published) == 0
    assert budget.used() == 0  # a failed call was not recorded as spent quota


# -- poll_forever ----------------------------------------------------------


async def test_poll_forever_stops_geocoding_failure_without_polling(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    geocoder = _FakeGeocoder(fail=True)
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    mqtt = _FakeMqtt()
    stop_event = asyncio.Event()

    await poll_forever(provider, geocoder, budget, mqtt, ROUTE, interval_seconds=1, stop_event=stop_event)

    assert provider.calls == 0
    assert len(mqtt.published) == 0


async def test_poll_forever_polls_once_immediately_then_stops():
    provider = _FakeProvider(calc=_calc_with_one_route())
    geocoder = _FakeGeocoder()
    mqtt = _FakeMqtt()
    stop_event = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.05)
        stop_event.set()

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        budget = BudgetGuard(path=Path(tmp) / "usage.json", monthly_limit=100)
        stopper = asyncio.create_task(stop_soon())
        # Long interval -- if poll_forever didn't poll immediately on entry,
        # this test would time out waiting for a second cycle instead.
        await poll_forever(
            provider, geocoder, budget, mqtt, ROUTE, interval_seconds=3600, stop_event=stop_event
        )
        await stopper

    assert provider.calls == 1
    assert len(mqtt.published) == 1
