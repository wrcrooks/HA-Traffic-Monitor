"""Locks in the delay/traffic_level correction from ROADMAP.md section 4,
using the real numbers captured from a live route (Magnolia, TX -> Spring,
TX) rather than invented ones."""
from app.models import RouteSummary, TrafficLevel


def test_delay_is_live_minus_typical_not_the_raw_traffic_delay_field():
    # Real captured values: travelTimeInSeconds=1702, noTrafficTravelTimeInSeconds=1535,
    # trafficDelayInSeconds=0 (TomTom's incident-relative-to-historic-norm number).
    summary = RouteSummary(
        duration_seconds=1702,
        duration_typical_seconds=1535,
        incident_delay_seconds=0,
        length_meters=33370,
    )
    assert summary.delay_seconds == 167
    assert summary.traffic_level == TrafficLevel.LIGHT  # 167/1535 ~= 10.9%


def test_delay_never_negative():
    # A route that's currently running faster than its own "typical" baseline
    # (can happen at the boundary) should read as free_flow, not a negative delay.
    summary = RouteSummary(
        duration_seconds=1000,
        duration_typical_seconds=1200,
        incident_delay_seconds=0,
        length_meters=10000,
    )
    assert summary.delay_seconds == 0
    assert summary.traffic_level == TrafficLevel.FREE_FLOW


def test_traffic_level_thresholds():
    def level_for(duration: int, typical: int) -> TrafficLevel:
        return RouteSummary(
            duration_seconds=duration,
            duration_typical_seconds=typical,
            incident_delay_seconds=0,
            length_meters=1000,
        ).traffic_level

    assert level_for(1000, 1000) == TrafficLevel.FREE_FLOW  # 0%
    assert level_for(1040, 1000) == TrafficLevel.FREE_FLOW  # 4%
    assert level_for(1100, 1000) == TrafficLevel.LIGHT  # 10%
    assert level_for(1300, 1000) == TrafficLevel.MODERATE  # 30%
    assert level_for(1600, 1000) == TrafficLevel.HEAVY  # 60%
