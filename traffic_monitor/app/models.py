"""
Domain models shared by the routing provider layer, the geocode cache, and
(from M2 onward) the MQTT publisher. Kept provider-agnostic: nothing here
knows about TomTom specifically -- see providers/tomtom.py for the mapping
from TomTom's JSON shape onto these types.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    lat: float
    lon: float

    def as_param(self) -> str:
        """TomTom's `lat,lon` path-segment format."""
        return f"{self.lat},{self.lon}"


class GeocodeResult(BaseModel):
    query: str
    point: GeoPoint
    formatted_address: str


class TrafficLevel(str, Enum):
    FREE_FLOW = "free_flow"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"


class RouteSummary(BaseModel):
    """Maps onto TomTom's `summary` object. Field names below are ours;
    see providers/tomtom.py for what each one is read from.

    IMPORTANT: `trafficDelayInSeconds` (-> incident_delay_seconds) is NOT
    delay relative to free-flow. It's delay from incidents relative to the
    *historic-typical* time for that hour, and reads 0 during ordinary
    congestion. Verified against a real route (see ROADMAP.md section 4's
    correction note) before this was assumed. `delay_seconds` below is the
    one that answers "how much longer than best-case, right now."
    """

    duration_seconds: int
    duration_typical_seconds: int
    incident_delay_seconds: int
    length_meters: int
    departure_time: datetime | None = None
    arrival_time: datetime | None = None

    @property
    def delay_seconds(self) -> int:
        return max(0, self.duration_seconds - self.duration_typical_seconds)

    @property
    def traffic_level(self) -> TrafficLevel:
        if self.duration_typical_seconds <= 0:
            return TrafficLevel.FREE_FLOW
        ratio = self.delay_seconds / self.duration_typical_seconds
        if ratio < 0.05:
            return TrafficLevel.FREE_FLOW
        if ratio < 0.20:
            return TrafficLevel.LIGHT
        if ratio < 0.50:
            return TrafficLevel.MODERATE
        return TrafficLevel.HEAVY


class RouteAlternative(BaseModel):
    """One route out of a calculateRoute response.

    `index` is only a position within *this* response -- TomTom assigns no
    stable identifier across calls, and traffic conditions can reorder
    alternatives between polls. Do not persist `index` as a way to
    remember "the user's route"; that's what route pinning (ROADMAP.md
    section 5, M5) exists to solve, via `points` geometry instead.
    """

    index: int
    summary: RouteSummary
    points: list[GeoPoint] = Field(default_factory=list)


class RouteCalculation(BaseModel):
    routes: list[RouteAlternative]
    queried_at: datetime


class RouteConfig(BaseModel):
    """M2's temporary single-route config, sourced directly from add-on
    options. Replaced by the multi-route /data/routes.json model in M3
    (ROADMAP.md) -- route_id will become a generated slug rather than a
    fixed constant once there can be more than one."""

    route_id: str
    name: str
    origin_address: str
    destination_address: str
    avoid_tolls: bool = False
