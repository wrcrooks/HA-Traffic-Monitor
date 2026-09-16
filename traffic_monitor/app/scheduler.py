"""
M2 minimal scheduler: a single hardcoded route (from add-on options),
polled at a fixed interval and published to MQTT. Multi-route config with
per-route active-window scheduling (ROADMAP.md section 2 / M3) replaces
this -- kept deliberately simple here so M2 proves the poll -> MQTT ->
entity pipeline end to end before that complexity is added.
"""
from __future__ import annotations

import asyncio
import logging

from app.budget import BudgetGuard
from app.geocache import CachedGeocoder
from app.models import RouteConfig
from app.mqtt import MqttPublisher
from app.providers.base import ProviderError
from app.providers.tomtom import TomTomProvider

logger = logging.getLogger("traffic_monitor.scheduler")


async def poll_forever(
    provider: TomTomProvider,
    geocoder: CachedGeocoder,
    budget: BudgetGuard,
    mqtt: MqttPublisher,
    route: RouteConfig,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    try:
        origin = await geocoder.geocode(route.origin_address)
        destination = await geocoder.geocode(route.destination_address)
    except ProviderError as exc:
        logger.error("Could not geocode route %r: %s -- polling will not start", route.name, exc)
        return

    logger.info(
        "Resolved %r: %s -> %s. Polling every %.0fs.",
        route.name,
        origin.formatted_address,
        destination.formatted_address,
        interval_seconds,
    )

    while not stop_event.is_set():
        await _poll_once(provider, budget, mqtt, route, origin.point, destination.point)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


async def _poll_once(provider, budget, mqtt, route, origin_point, destination_point) -> None:
    if not budget.allow():
        logger.error(
            "Monthly API budget exhausted (%d/%d) -- skipping poll for %r",
            budget.used(),
            budget.monthly_limit,
            route.name,
        )
        return

    try:
        calc = await provider.calculate_route(
            origin_point, destination_point, avoid_tolls=route.avoid_tolls, max_alternatives=0
        )
        budget.record()
    except ProviderError as exc:
        logger.warning("Failed to poll %r: %s", route.name, exc)
        return

    if not calc.routes:
        logger.warning("No route returned for %r", route.name)
        return

    await mqtt.publish_state(route, calc.routes[0])
    logger.debug(
        "Published %r: %.1f min live, traffic=%s",
        route.name,
        calc.routes[0].summary.duration_seconds / 60,
        calc.routes[0].summary.traffic_level.value,
    )
