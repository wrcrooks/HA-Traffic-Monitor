from __future__ import annotations

from app.geocache import CachedGeocoder, GeocodeCache
from app.models import GeocodeResult, GeoPoint


class _FakeProvider:
    """Records every call so tests can assert the cache actually prevented
    a second network hit."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def geocode(self, address: str) -> GeocodeResult:
        self.calls.append(address)
        return GeocodeResult(
            query=address, point=GeoPoint(lat=1.0, lon=2.0), formatted_address=f"Resolved: {address}"
        )


def test_put_then_get_roundtrip(tmp_path):
    cache = GeocodeCache(tmp_path / "geocache.json")
    result = GeocodeResult(
        query="123 Main St", point=GeoPoint(lat=30.1, lon=-95.6), formatted_address="123 Main St, TX"
    )
    cache.put("123 Main St", result)

    fetched = cache.get("123 Main St")
    assert fetched is not None
    assert fetched.point.lat == 30.1
    assert fetched.formatted_address == "123 Main St, TX"


def test_get_miss_returns_none(tmp_path):
    cache = GeocodeCache(tmp_path / "geocache.json")
    assert cache.get("nowhere") is None


def test_lookup_is_case_and_whitespace_insensitive(tmp_path):
    cache = GeocodeCache(tmp_path / "geocache.json")
    result = GeocodeResult(query="x", point=GeoPoint(lat=1, lon=2), formatted_address="x")
    cache.put("  123 Main St, Springfield  ", result)
    assert cache.get("123 main st,   springfield") is not None


def test_persists_across_instances(tmp_path):
    path = tmp_path / "geocache.json"
    result = GeocodeResult(query="x", point=GeoPoint(lat=1, lon=2), formatted_address="x")
    GeocodeCache(path).put("some address", result)

    reloaded = GeocodeCache(path)
    assert reloaded.get("some address") is not None
    assert len(reloaded) == 1


async def test_cached_geocoder_calls_provider_once_for_repeated_address(tmp_path):
    provider = _FakeProvider()
    cache = GeocodeCache(tmp_path / "geocache.json")
    geocoder = CachedGeocoder(provider, cache)

    first = await geocoder.geocode("123 Main St")
    second = await geocoder.geocode("123 Main St")

    assert first.point == second.point
    assert provider.calls == ["123 Main St"]  # only called once
