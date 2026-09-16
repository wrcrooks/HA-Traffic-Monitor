"""
Per-route polling (ROADMAP.md section 2 / M3). One poll_route_forever task
runs per enabled route (managed by manager.py), each on its own interval,
respecting its own active-window schedule.

`_poll_once` deliberately returns the fresh result (or None on any skip/
failure) rather than publishing directly -- that lets poll_route_forever
own the stale/in_active_window bookkeeping in one place: `stale` is True
whenever *this* tick didn't produce a fresh number, whether that's because
the route is outside its active window, the API budget is exhausted, or
the provider call failed. The last successfully fetched result keeps
being republished (with stale=True) so entities don't go blank between
successful polls -- only the attribute changes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.budget import BudgetGuard
from app.geocache import CachedGeocoder
from app.models import Route, RouteAlternative
from app.mqtt import MqttPublisher
from app.providers.base import ProviderError
from app.providers.tomtom import TomTomProvider

logger = logging.getLogger("traffic_monitor.scheduler")


async def poll_route_forever(
    provider: TomTomProvider,
    geocoder: CachedGeocoder,
    budget: BudgetGuard,
    mqtt: MqttPublisher,
    route: Route,
    stop_event: asyncio.Event,
) -> None:
    try:
        origin = await geocoder.geocode(route.origin_address)
        destination = await geocoder.geocode(route.destination_address)
    except ProviderError as exc:
        logger.error("Could not geocode route %r: %s -- polling will not start", route.name, exc)
        return

    windowed = bool(route.schedule.windows)
    logger.info(
        "Resolved %r: %s -> %s. Polling every %d min%s.",
        route.name,
        origin.formatted_address,
        destination.formatted_address,
        route.poll_interval_minutes,
        " (windowed)" if windowed else "",
    )

    last_result: RouteAlternative | None = None

    while not stop_event.is_set():
        now = datetime.now().astimezone()
        in_window = route.schedule.is_active(now)

        fresh: RouteAlternative | None = None
        if in_window:
            fresh = await _poll_once(provider, budget, route, origin.point, destination.point)
            if fresh is not None:
                last_result = fresh
        else:
            logger.debug("Route %r is outside its active window -- skipping poll", route.name)

        if last_result is not None:
            await mqtt.publish_state(route, last_result, stale=(fresh is None), in_active_window=in_window)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=route.poll_interval_minutes * 60)
        except asyncio.TimeoutError:
            pass


async def _poll_once(
    provider: TomTomProvider, budget: BudgetGuard, route: Route, origin_point, destination_point
) -> RouteAlternative | None:
    if not budget.allow():
        logger.error(
            "Monthly API budget exhausted (%d/%d) -- skipping poll for %r",
            budget.used(),
            budget.monthly_limit,
            route.name,
        )
        return None

    try:
        calc = await provider.calculate_route(
            origin_point, destination_point, avoid_tolls=route.avoid_tolls, max_alternatives=0
        )
        budget.record()
    except ProviderError as exc:
        logger.warning("Failed to poll %r: %s", route.name, exc)
        return None

    if not calc.routes:
        logger.warning("No route returned for %r", route.name)
        return None

    logger.debug(
        "Polled %r: %.1f min live, traffic=%s",
        route.name,
        calc.routes[0].summary.duration_seconds / 60,
        calc.routes[0].summary.traffic_level.value,
    )
    return calc.routes[0]
