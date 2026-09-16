"""
Domain models shared by the routing provider layer, the geocode cache, and
(from M2 onward) the MQTT publisher. Kept provider-agnostic: nothing here
knows about TomTom specifically -- see providers/tomtom.py for the mapping
from TomTom's JSON shape onto these types.
"""
from __future__ import annotations

from datetime import datetime, time
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


class TimeWindow(BaseModel):
    """An active-polling window on a single day. `start` must be <= `end`
    -- windows spanning midnight aren't supported in v1 (ROADMAP.md
    section 2); model two windows instead (e.g. 22:00-23:59 and
    00:00-02:00) if that's ever needed."""

    start: time
    end: time


class Schedule(BaseModel):
    """When a route should actually be polled (ROADMAP.md section 2's API
    budget discussion -- this is what makes many routes fit inside
    TomTom's free tier). An empty `windows` list means "always active";
    that's the default so a route works with no configuration beyond an
    origin/destination.

    `days` uses Python's Monday=0 convention (datetime.weekday()).
    """

    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    windows: list[TimeWindow] = Field(default_factory=list)

    def is_active(self, at: datetime) -> bool:
        if not self.windows:
            return True
        if at.weekday() not in self.days:
            return False
        t = at.time()
        return any(w.start <= t <= w.end for w in self.windows)


class Route(BaseModel):
    """A user-configured route (ROADMAP.md M3), persisted in
    /data/routes.json via RoutesStore. Replaces M2's single hardcoded
    RouteConfig sourced from add-on options."""

    id: str
    name: str
    origin_address: str
    destination_address: str
    avoid_tolls: bool = False
    poll_interval_minutes: int = Field(15, ge=1, le=1440)
    schedule: Schedule = Field(default_factory=Schedule)
    enabled: bool = True
    selected_alternative_points: list[GeoPoint] | None = None
    """The polyline of the alternative the user picked in the M4 preview
    UI, captured here so M5's route pinning (ROADMAP.md section 5) has
    something to reconstruct against. Not yet consumed by the scheduler
    -- until M5, every poll still calculates fresh (fastest-by-TomTom's-
    current-ranking) regardless of what's stored here. None means the
    user never picked a specific alternative (or picked the default
    fastest one), which behaves identically to today either way."""


class RoutesFile(BaseModel):
    """The on-disk shape of /data/routes.json. schema_version exists from
    day one, before any migration is actually needed, so the migration
    mechanism itself (see routes_store.py) is exercised and tested well
    before a real schema change ever depends on it."""

    schema_version: int = 1
    routes: list[Route] = Field(default_factory=list)
