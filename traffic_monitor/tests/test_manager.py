from __future__ import annotations

import asyncio

import pytest

from app.manager import RouteManager
from app.models import Route
from app.routes_store import RoutesStore


class FakePoller:
    """Stands in for scheduler.poll_route_forever: records which routes
    started/stopped without making any real network calls, so manager
    tests exercise only RouteManager's own task-lifecycle logic."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []

    async def __call__(self, provider, geocoder, budget, mqtt, route: Route, stop_event: asyncio.Event) -> None:
        self.started.append(route.id)
        await stop_event.wait()
        self.stopped.append(route.id)


class FakeMqtt:
    def __init__(self) -> None:
        self.discovery_calls: list[list[str]] = []
        self.cleared: list[str] = []

    async def publish_discovery(self, routes: list[Route]) -> None:
        self.discovery_calls.append([r.id for r in routes])

    async def clear_route(self, route: Route) -> None:
        self.cleared.append(route.id)


def _route(id: str, enabled: bool = True) -> Route:
    return Route(id=id, name=id, origin_address="A", destination_address="B", enabled=enabled)


def _manager(tmp_path) -> tuple[RouteManager, FakePoller, FakeMqtt, RoutesStore]:
    store = RoutesStore(tmp_path / "routes.json")
    mqtt = FakeMqtt()
    poller = FakePoller()
    manager = RouteManager(
        provider=object(), geocoder=object(), budget=object(), mqtt=mqtt, store=store, poll_fn=poller
    )
    return manager, poller, mqtt, store


async def test_start_all_starts_a_task_per_enabled_route_only(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    store.create(_route("a"))
    store.create(_route("b", enabled=False))
    store.create(_route("c"))

    await manager.start_all()
    await asyncio.sleep(0.01)  # let the tasks actually run up to stop_event.wait()

    assert manager.running_route_ids == {"a", "c"}
    assert set(poller.started) == {"a", "c"}

    await manager.shutdown()


async def test_create_route_starts_task_and_publishes_discovery(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)

    created = await manager.create_route(_route("new"))
    await asyncio.sleep(0.01)

    assert created.id == "new"
    assert store.get("new") is not None
    assert "new" in manager.running_route_ids
    assert mqtt.discovery_calls == [["new"]]

    await manager.shutdown()


async def test_create_route_disabled_does_not_start_task(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)

    await manager.create_route(_route("off", enabled=False))
    await asyncio.sleep(0.01)

    assert "off" not in manager.running_route_ids
    assert mqtt.discovery_calls == [["off"]]  # discovery still published -- entity should exist, just unpolled

    await manager.shutdown()


async def test_create_route_duplicate_id_raises(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    await manager.create_route(_route("dup"))

    with pytest.raises(ValueError):
        await manager.create_route(_route("dup"))

    await manager.shutdown()


async def test_update_route_restarts_its_task(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    await manager.create_route(_route("r"))
    await asyncio.sleep(0.01)
    old_task = manager._tasks["r"]

    updated = _route("r").model_copy(update={"name": "Renamed"})
    await manager.update_route("r", updated)
    await asyncio.sleep(0.01)

    assert poller.stopped == ["r"]  # the old task was told to stop and did
    assert poller.started == ["r", "r"]  # started once originally, once again after update
    assert manager._tasks["r"] is not old_task
    assert store.get("r").name == "Renamed"

    await manager.shutdown()


async def test_update_route_to_disabled_stops_without_restarting(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    await manager.create_route(_route("r"))
    await asyncio.sleep(0.01)

    disabled = _route("r", enabled=False)
    await manager.update_route("r", disabled)
    await asyncio.sleep(0.01)

    assert "r" not in manager.running_route_ids
    assert poller.stopped == ["r"]

    await manager.shutdown()


async def test_delete_route_stops_task_and_clears_mqtt(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    await manager.create_route(_route("r"))
    await asyncio.sleep(0.01)

    removed = await manager.delete_route("r")

    assert removed is not None
    assert removed.id == "r"
    assert "r" not in manager.running_route_ids
    assert poller.stopped == ["r"]
    assert mqtt.cleared == ["r"]
    assert store.get("r") is None


async def test_delete_missing_route_returns_none_and_does_not_clear_mqtt(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    removed = await manager.delete_route("nope")
    assert removed is None
    assert mqtt.cleared == []


async def test_on_mqtt_connect_publishes_discovery_for_all_known_routes(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    store.create(_route("a"))
    store.create(_route("b"))

    await manager.on_mqtt_connect()

    assert mqtt.discovery_calls == [["a", "b"]]


async def test_shutdown_stops_every_running_task(tmp_path):
    manager, poller, mqtt, store = _manager(tmp_path)
    store.create(_route("a"))
    store.create(_route("b"))
    await manager.start_all()
    await asyncio.sleep(0.01)

    await manager.shutdown()

    assert manager.running_route_ids == set()
    assert set(poller.stopped) == {"a", "b"}
