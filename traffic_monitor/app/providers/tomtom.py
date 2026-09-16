"""
TomTom implementation of TrafficProvider.

API reference notes worth keeping close to the code (verified against
docs.tomtom.com and live responses during M1, not assumed):

- Auth failures come back as HTTP 401 ("missing/invalid credentials"), not
  403 as commonly assumed from generic REST conventions. A 403 is also
  treated as an auth failure here (TomTom docs describe it for a valid key
  lacking product access), so both are handled the same way.
- Rate limit is 5 requests/second per key; exceeding it returns 429.
- `trafficDelayInSeconds` is delay from incidents relative to the
  *historic-typical* time for that hour, not relative to free-flow -- see
  app.models.RouteSummary and ROADMAP.md section 4.
- Route reconstruction (`supportingPoints`) requires POST with a body of
  `{"supportingPoints": [{"latitude": .., "longitude": ..}, ...]}` -- a
  plain array, not GeoJSON. An earlier GeoJSON MultiPoint attempt was
  rejected with `INVALID_REQUEST` before this shape was confirmed live.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import httpx

from app.models import GeocodeResult, GeoPoint, RouteAlternative, RouteCalculation, RouteSummary
from app.providers.base import (
    AuthenticationError,
    GeocodeNotFoundError,
    ProviderUnavailableError,
    RateLimitedError,
    TrafficProvider,
)

logger = logging.getLogger("traffic_monitor.providers.tomtom")

DEFAULT_BASE_URL = "https://api.tomtom.com"


@dataclass
class TomTomConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 10.0
    max_retries: int = 3
    requests_per_second: float = 5.0


class _RateLimiter:
    """Keeps calls under TomTom's 5 req/s cap. A rolling window over the
    last `rate` requests, rather than a fixed per-second bucket, so a
    burst right at a second boundary can't sneak through at ~2x rate."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._rate:
                wait = 1.0 - (now - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > 1.0:
                    self._timestamps.popleft()
            self._timestamps.append(time.monotonic())


class TomTomProvider(TrafficProvider):
    def __init__(self, config: TomTomConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._owns_client = client is None
        self._limiter = _RateLimiter(config.requests_per_second)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "TomTomProvider":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- transport -----------------------------------------------------

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> dict:
        url = f"{self._config.base_url}{path}"
        params = {**(params or {}), "key": self._config.api_key}

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            await self._limiter.acquire()
            try:
                response = await self._client.request(method, url, params=params, json=json_body)
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("TomTom request timed out (attempt %d): %s", attempt + 1, exc)
                await self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("TomTom request failed (attempt %d): %s", attempt + 1, exc)
                await self._backoff(attempt)
                continue

            if response.status_code in (401, 403):
                raise AuthenticationError(
                    f"TomTom rejected the API key (HTTP {response.status_code}): {response.text}"
                )
            if response.status_code == 429:
                raise RateLimitedError(f"TomTom rate limit hit: {response.text}")
            if response.status_code >= 500:
                last_exc = ProviderUnavailableError(
                    f"TomTom server error (HTTP {response.status_code}): {response.text}"
                )
                logger.warning("TomTom server error (attempt %d): %s", attempt + 1, response.text)
                await self._backoff(attempt)
                continue
            if response.status_code >= 400:
                # Not retryable -- a malformed request will fail the same
                # way every time.
                raise ProviderUnavailableError(
                    f"TomTom rejected the request (HTTP {response.status_code}): {response.text}"
                )

            return response.json()

        assert last_exc is not None
        raise ProviderUnavailableError(
            f"TomTom request failed after {self._config.max_retries + 1} attempts"
        ) from last_exc

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(min(0.5 * (2**attempt), 5.0))

    # -- geocoding -------------------------------------------------------

    async def geocode(self, address: str) -> GeocodeResult:
        data = await self._send(
            "GET",
            f"/search/2/geocode/{quote(address, safe='')}.json",
            params={"limit": "1"},
        )
        results = data.get("results") or []
        if not results:
            raise GeocodeNotFoundError(f"No geocoding results for {address!r}")
        result = results[0]
        position = result["position"]
        return GeocodeResult(
            query=address,
            point=GeoPoint(lat=position["lat"], lon=position["lon"]),
            formatted_address=result.get("address", {}).get("freeformAddress", address),
        )

    # -- routing -----------------------------------------------------------

    async def calculate_route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        *,
        avoid_tolls: bool = False,
        max_alternatives: int = 5,
        include_geometry: bool = False,
        supporting_points: list[GeoPoint] | None = None,
    ) -> RouteCalculation:
        route_repr = "polyline" if include_geometry else "summaryOnly"
        locations = f"{origin.as_param()}:{destination.as_param()}"

        params = {
            "traffic": "true",
            "computeTravelTimeFor": "all",
            "routeRepresentation": route_repr,
        }
        if avoid_tolls:
            params["avoid"] = "tollRoads"

        if supporting_points:
            # Route reconstruction: POST with the pinned geometry, no
            # maxAlternatives (there's exactly one route to reconstruct).
            body = {
                "supportingPoints": [
                    {"latitude": p.lat, "longitude": p.lon} for p in supporting_points
                ]
            }
            data = await self._send(
                "POST", f"/routing/1/calculateRoute/{locations}/json", params=params, json_body=body
            )
        else:
            params["maxAlternatives"] = str(max_alternatives)
            data = await self._send("GET", f"/routing/1/calculateRoute/{locations}/json", params=params)

        routes = [
            _parse_route(i, raw) for i, raw in enumerate(data.get("routes", []))
        ]
        return RouteCalculation(routes=routes, queried_at=datetime.now().astimezone())


def _parse_route(index: int, raw: dict) -> RouteAlternative:
    summary = _parse_summary(raw["summary"])
    points: list[GeoPoint] = []
    for leg in raw.get("legs", []):
        points.extend(GeoPoint(lat=p["latitude"], lon=p["longitude"]) for p in leg.get("points", []))
    return RouteAlternative(index=index, summary=summary, points=points)


def _parse_summary(raw: dict) -> RouteSummary:
    return RouteSummary(
        duration_seconds=raw["travelTimeInSeconds"],
        duration_typical_seconds=raw.get("noTrafficTravelTimeInSeconds", raw["travelTimeInSeconds"]),
        incident_delay_seconds=raw.get("trafficDelayInSeconds", 0),
        length_meters=raw["lengthInMeters"],
        departure_time=_parse_dt(raw.get("departureTime")),
        arrival_time=_parse_dt(raw.get("arrivalTime")),
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
