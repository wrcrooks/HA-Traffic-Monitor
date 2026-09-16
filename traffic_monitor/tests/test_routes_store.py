from __future__ import annotations

import json

import pytest

from app.models import Route
from app.routes_store import RoutesStore, new_route_id


def _route(id: str = "r1", name: str = "Test Route") -> Route:
    return Route(id=id, name=name, origin_address="A", destination_address="B")


def test_starts_empty(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    assert store.list() == []
    assert store.get("nope") is None


def test_create_then_get(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    store.create(_route())
    fetched = store.get("r1")
    assert fetched is not None
    assert fetched.name == "Test Route"


def test_create_duplicate_id_raises(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    store.create(_route())
    with pytest.raises(ValueError):
        store.create(_route())


def test_update_replaces_route(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    store.create(_route())
    updated = _route().model_copy(update={"name": "Renamed"})
    store.update("r1", updated)
    assert store.get("r1").name == "Renamed"


def test_update_missing_id_raises(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    with pytest.raises(KeyError):
        store.update("nope", _route())


def test_delete_returns_removed_route(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    store.create(_route())
    removed = store.delete("r1")
    assert removed is not None
    assert removed.id == "r1"
    assert store.list() == []


def test_delete_missing_id_returns_none(tmp_path):
    store = RoutesStore(tmp_path / "routes.json")
    assert store.delete("nope") is None


def test_persists_across_instances(tmp_path):
    path = tmp_path / "routes.json"
    RoutesStore(path).create(_route())
    reloaded = RoutesStore(path)
    assert len(reloaded.list()) == 1
    assert reloaded.get("r1").name == "Test Route"


def test_file_carries_schema_version(tmp_path):
    path = tmp_path / "routes.json"
    RoutesStore(path).create(_route())
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 1


def test_migrates_schema_version_0_file(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text(
        json.dumps({"routes": [{"id": "old", "name": "Old Route", "origin_address": "A", "destination_address": "B"}]})
    )
    store = RoutesStore(path)  # no schema_version key at all -- version 0
    assert store.get("old") is not None
    assert store.get("old").name == "Old Route"


def test_corrupt_file_starts_empty_rather_than_crashing(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text("{not valid json")
    store = RoutesStore(path)
    assert store.list() == []


def test_new_route_id_is_unique_for_same_name():
    a = new_route_id("My Commute")
    b = new_route_id("My Commute")
    assert a != b
    assert a.startswith("my_commute_")


def test_new_route_id_handles_no_alnum_chars():
    assert new_route_id("!!!").startswith("route_")
