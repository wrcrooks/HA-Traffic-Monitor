"""
Permanent address -> coordinates cache. Addresses don't move, so once we've
geocoded one it should never cost another API call (see ROADMAP.md
section 2's budget discussion).

Deliberately provider-agnostic: it wraps any TrafficProvider, not just
TomTom, via CachedGeocoder below.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models import GeocodeResult, GeoPoint
from app.providers.base import TrafficProvider

logger = logging.getLogger("traffic_monitor.geocache")


def _normalize(address: str) -> str:
    return " ".join(address.strip().lower().split())


class GeocodeCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read geocode cache at %s: %s", self._path, exc)
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True))

    def get(self, address: str) -> GeocodeResult | None:
        entry = self._data.get(_normalize(address))
        if entry is None:
            return None
        return GeocodeResult(
            query=address,
            point=GeoPoint(lat=entry["lat"], lon=entry["lon"]),
            formatted_address=entry["formatted_address"],
        )

    def put(self, address: str, result: GeocodeResult) -> None:
        self._data[_normalize(address)] = {
            "lat": result.point.lat,
            "lon": result.point.lon,
            "formatted_address": result.formatted_address,
        }
        self._save()

    def __len__(self) -> int:
        return len(self._data)


class CachedGeocoder:
    """Wraps any TrafficProvider so repeated geocodes of the same address
    never hit the network (or the API budget) a second time."""

    def __init__(self, provider: TrafficProvider, cache: GeocodeCache) -> None:
        self._provider = provider
        self._cache = cache

    async def geocode(self, address: str) -> GeocodeResult:
        cached = self._cache.get(address)
        if cached is not None:
            return cached
        result = await self._provider.geocode(address)
        self._cache.put(address, result)
        return result
