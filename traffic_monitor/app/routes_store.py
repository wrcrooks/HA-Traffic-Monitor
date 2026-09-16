"""
Persistence for /data/routes.json (ROADMAP.md M3), replacing M2's single
hardcoded route sourced from add-on options.

schema_version exists in the file from day one, before any real migration
is needed, specifically so the migration path itself gets exercised and
tested now rather than being written from scratch under pressure the
first time a field actually needs to change shape.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from app.models import Route, RoutesFile

logger = logging.getLogger("traffic_monitor.routes_store")

CURRENT_SCHEMA_VERSION = 1


def new_route_id(name: str) -> str:
    """A readable slug where possible, unique regardless of collisions
    (two routes named the same thing, or a name with no alnum chars)."""
    slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    slug = slug or "route"
    return f"{slug}_{uuid.uuid4().hex[:8]}"


def _migrate(raw: dict) -> dict:
    version = raw.get("schema_version", 0)
    if version == 0:
        # No release ever shipped a version-0 file in practice (M3 is the
        # first with persisted routes.json) -- this step exists so the
        # mechanism is proven before it's ever load-bearing.
        raw = {"schema_version": 1, "routes": raw.get("routes", [])}
    return raw


class RoutesStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()

    def _load(self) -> RoutesFile:
        if not self._path.exists():
            return RoutesFile()
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not read %s: %s -- starting with no routes", self._path, exc)
            return RoutesFile()
        return RoutesFile.model_validate(_migrate(raw))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(self._data.model_dump_json(indent=2))

    def list(self) -> list[Route]:
        return list(self._data.routes)

    def get(self, route_id: str) -> Route | None:
        return next((r for r in self._data.routes if r.id == route_id), None)

    def create(self, route: Route) -> Route:
        if self.get(route.id) is not None:
            raise ValueError(f"route id {route.id!r} already exists")
        self._data.routes.append(route)
        self._save()
        return route

    def update(self, route_id: str, route: Route) -> Route:
        idx = next((i for i, r in enumerate(self._data.routes) if r.id == route_id), None)
        if idx is None:
            raise KeyError(route_id)
        self._data.routes[idx] = route
        self._save()
        return route

    def delete(self, route_id: str) -> Route | None:
        idx = next((i for i, r in enumerate(self._data.routes) if r.id == route_id), None)
        if idx is None:
            return None
        removed = self._data.routes.pop(idx)
        self._save()
        return removed
