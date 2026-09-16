"""Locks in the delay/traffic_level correction from ROADMAP.md section 4,
using the real numbers captured from a live route (Magnolia, TX -> Spring,
TX) rather than invented ones."""
from datetime import datetime

from app.models import RouteSummary, Schedule, TimeWindow, TrafficLevel


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


# -- Schedule.is_active (ROADMAP.md section 2's active-window feature) -----


def test_schedule_with_no_windows_is_always_active():
    schedule = Schedule(windows=[])
    # A Sunday (weekday()==6), not in the default Mon-Fri `days` -- still
    # active, because an empty windows list means "no windowing at all".
    sunday = datetime(2026, 9, 20, 3, 0)
    assert sunday.weekday() == 6
    assert schedule.is_active(sunday) is True


def test_schedule_inside_window_on_allowed_day_is_active():
    schedule = Schedule(days=[0, 1, 2, 3, 4], windows=[TimeWindow(start="07:00", end="09:00")])
    monday_8am = datetime(2026, 9, 14, 8, 0)  # a Monday
    assert monday_8am.weekday() == 0
    assert schedule.is_active(monday_8am) is True


def test_schedule_outside_window_time_is_inactive():
    schedule = Schedule(days=[0, 1, 2, 3, 4], windows=[TimeWindow(start="07:00", end="09:00")])
    monday_noon = datetime(2026, 9, 14, 12, 0)
    assert schedule.is_active(monday_noon) is False


def test_schedule_wrong_day_is_inactive_even_during_window_time():
    schedule = Schedule(days=[0, 1, 2, 3, 4], windows=[TimeWindow(start="07:00", end="09:00")])
    saturday_8am = datetime(2026, 9, 19, 8, 0)
    assert saturday_8am.weekday() == 5
    assert schedule.is_active(saturday_8am) is False


def test_schedule_with_multiple_windows_matches_either():
    schedule = Schedule(
        days=[0, 1, 2, 3, 4],
        windows=[TimeWindow(start="07:00", end="09:00"), TimeWindow(start="16:00", end="18:00")],
    )
    monday_5pm = datetime(2026, 9, 14, 17, 0)
    assert schedule.is_active(monday_5pm) is True
    monday_noon = datetime(2026, 9, 14, 12, 0)
    assert schedule.is_active(monday_noon) is False


def test_schedule_with_no_days_is_never_active_even_with_windows():
    schedule = Schedule(days=[], windows=[TimeWindow(start="00:00", end="23:59")])
    assert schedule.is_active(datetime(2026, 9, 14, 12, 0)) is False
