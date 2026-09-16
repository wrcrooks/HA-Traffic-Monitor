from __future__ import annotations

import asyncio
from datetime import datetime

from app.budget import BudgetGuard
from app.models import (
    GeocodeResult,
    GeoPoint,
    Route,
    RouteAlternative,
    RouteCalculation,
    RouteSummary,
    Schedule,
    TimeWindow,
)
from app.providers.base import ProviderError
from app.scheduler import _poll_once, poll_route_forever

ROUTE = Route(
    id="commute",
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
        self.published: list[tuple] = []  # (route, alternative, stale, in_active_window)

    async def publish_state(self, route, alternative, *, stale=False, in_active_window=True):
        self.published.append((route, alternative, stale, in_active_window))


def _calc_with_one_route() -> RouteCalculation:
    return RouteCalculation(
        routes=[RouteAlternative(index=0, summary=SUMMARY)], queried_at=datetime.now().astimezone()
    )


# -- _poll_once ------------------------------------------------------------


async def test_poll_once_returns_alternative_and_records_budget(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)

    result = await _poll_once(provider, budget, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert provider.calls == 1
    assert budget.used() == 1
    assert result is not None
    assert result.summary.duration_seconds == 1702


async def test_poll_once_returns_none_when_budget_exhausted(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=1)
    budget.record(1)  # already exhausted

    result = await _poll_once(provider, budget, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert provider.calls == 0  # never even called the provider
    assert result is None


async def test_poll_once_returns_none_on_provider_error(tmp_path):
    provider = _FakeProvider(error=ProviderError("boom"))
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)

    # Must not raise -- a single bad poll should not kill the loop.
    result = await _poll_once(provider, budget, ROUTE, GeoPoint(lat=1, lon=2), GeoPoint(lat=3, lon=4))

    assert result is None
    assert budget.used() == 0  # a failed call was not recorded as spent quota


# -- poll_route_forever ------------------------------------------------------


async def test_poll_route_forever_stops_on_geocoding_failure_without_polling(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    geocoder = _FakeGeocoder(fail=True)
    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    mqtt = _FakeMqtt()
    stop_event = asyncio.Event()

    await poll_route_forever(provider, geocoder, budget, mqtt, ROUTE, stop_event)

    assert provider.calls == 0
    assert len(mqtt.published) == 0


async def test_poll_route_forever_polls_once_immediately_publishes_fresh(tmp_path):
    provider = _FakeProvider(calc=_calc_with_one_route())
    geocoder = _FakeGeocoder()
    mqtt = _FakeMqtt()
    stop_event = asyncio.Event()
    route = ROUTE.model_copy(update={"poll_interval_minutes": 60})  # long interval

    async def stop_soon():
        await asyncio.sleep(0.05)
        stop_event.set()

    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    stopper = asyncio.create_task(stop_soon())
    await poll_route_forever(provider, geocoder, budget, mqtt, route, stop_event)
    await stopper

    assert provider.calls == 1
    assert len(mqtt.published) == 1
    _, alt, stale, in_window = mqtt.published[0]
    assert stale is False
    assert in_window is True
    assert alt.summary.duration_seconds == 1702


async def test_poll_route_forever_outside_window_publishes_last_result_as_stale(tmp_path):
    """A route with a window that's never active right now should never
    call the provider, but if it already has a last-known result (it
    doesn't here, so nothing should publish at all)."""
    provider = _FakeProvider(calc=_calc_with_one_route())
    geocoder = _FakeGeocoder()
    mqtt = _FakeMqtt()
    stop_event = asyncio.Event()
    # A window that can never be active: no days at all.
    route = ROUTE.model_copy(
        update={
            "poll_interval_minutes": 60,
            "schedule": Schedule(days=[], windows=[TimeWindow(start="00:00", end="23:59")]),
        }
    )

    async def stop_soon():
        await asyncio.sleep(0.05)
        stop_event.set()

    budget = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    stopper = asyncio.create_task(stop_soon())
    await poll_route_forever(provider, geocoder, budget, mqtt, route, stop_event)
    await stopper

    assert provider.calls == 0  # never polled -- always outside its window
    assert len(mqtt.published) == 0  # and never had a result to (re)publish either
