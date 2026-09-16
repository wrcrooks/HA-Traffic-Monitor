"""
Keeps the set of running per-route poll tasks in sync with RoutesStore as
routes are created/updated/deleted through the API (ROADMAP.md M3). One
asyncio task per enabled route; the API layer (api.py) should always go
through RouteManager rather than RoutesStore directly, so a write always
gets its side effects (starting/stopping the poll task, publishing or
clearing MQTT discovery).

`poll_fn` is injectable (defaults to scheduler.poll_route_forever) purely
so tests can swap in a lightweight stub instead of a task that makes real
network calls -- production code never needs to pass it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.budget import BudgetGuard
from app.geocache import CachedGeocoder
from app.models import Route
from app.mqtt import MqttPublisher
from app.providers.tomtom import TomTomProvider
from app.routes_store import RoutesStore
from app.scheduler import poll_route_forever

logger = logging.getLogger("traffic_monitor.manager")

PollFn = Callable[
    [TomTomProvider, CachedGeocoder, BudgetGuard, MqttPublisher, Route, asyncio.Event], Awaitable[None]
]


class RouteManager:
    def __init__(
        self,
        provider: TomTomProvider,
        geocoder: CachedGeocoder,
        budget: BudgetGuard,
        mqtt: MqttPublisher,
        store: RoutesStore,
        poll_fn: PollFn = poll_route_forever,
    ) -> None:
        self._provider = provider
        self._geocoder = geocoder
        self._budget = budget
        self._mqtt = mqtt
        self._store = store
        self._poll_fn = poll_fn
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, asyncio.Event] = {}

    @property
    def running_route_ids(self) -> set[str]:
        return set(self._tasks)

    async def start_all(self) -> None:
        for route in self._store.list():
            if route.enabled:
                self._start(route)
            else:
                logger.info("Route %r is disabled -- not starting a poll task", route.name)

    async def on_mqtt_connect(self) -> None:
        """Passed to MqttPublisher.run() as on_connect -- republishes
        discovery for every known route on first connect and every
        reconnect (a broker that lost its retained-message store needs
        this to recover cleanly)."""
        await self._mqtt.publish_discovery(self._store.list())

    def _start(self, route: Route) -> None:
        stop_event = asyncio.Event()
        self._stop_events[route.id] = stop_event
        self._tasks[route.id] = asyncio.create_task(
            self._poll_fn(self._provider, self._geocoder, self._budget, self._mqtt, route, stop_event),
            name=f"poll:{route.id}",
        )

    async def _stop(self, route_id: str) -> None:
        stop_event = self._stop_events.pop(route_id, None)
        task = self._tasks.pop(route_id, None)
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
            except asyncio.CancelledError:
                pass

    async def create_route(self, route: Route) -> Route:
        created = self._store.create(route)
        await self._mqtt.publish_discovery([created])
        if created.enabled:
            self._start(created)
        return created

    async def update_route(self, route_id: str, updated: Route) -> Route:
        await self._stop(route_id)
        saved = self._store.update(route_id, updated)
        await self._mqtt.publish_discovery([saved])
        if saved.enabled:
            self._start(saved)
        return saved

    async def delete_route(self, route_id: str) -> Route | None:
        await self._stop(route_id)
        removed = self._store.delete(route_id)
        if removed is not None:
            await self._mqtt.clear_route(removed)
        return removed

    async def shutdown(self) -> None:
        for route_id in list(self._tasks):
            await self._stop(route_id)
