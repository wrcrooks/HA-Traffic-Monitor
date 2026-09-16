"""
The TrafficProvider interface. Everything above this layer (the scheduler,
the MQTT publisher, the UI's route preview) should depend only on this
module and app.models, never on providers.tomtom directly -- that's what
keeps a future HERE/Mapbox provider a drop-in rather than a rewrite (see
ROADMAP.md decision D6).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import GeocodeResult, GeoPoint, RouteCalculation


class ProviderError(Exception):
    """Base class for all traffic-provider failures."""


class AuthenticationError(ProviderError):
    """The API key was rejected or lacks access to the required product."""


class RateLimitedError(ProviderError):
    """The provider is throttling this key (HTTP 429)."""


class GeocodeNotFoundError(ProviderError):
    """The address query returned no results."""


class ProviderUnavailableError(ProviderError):
    """Network failure, or repeated 5xx after retries were exhausted."""


class TrafficProvider(ABC):
    @abstractmethod
    async def geocode(self, address: str) -> GeocodeResult:
        """Resolve a free-text address to coordinates.

        Raises GeocodeNotFoundError if there are no results,
        AuthenticationError / RateLimitedError / ProviderUnavailableError
        on provider failures.
        """

    @abstractmethod
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
        """Calculate one or more routes between origin and destination.

        `supporting_points`, when given, requests route *reconstruction*
        through those points instead of a fresh shortest/fastest search --
        this is the mechanism route pinning (ROADMAP.md section 5) is
        built on. `include_geometry` controls whether full polylines are
        returned (needed for the map UI, not for a routine poll).
        """
