from __future__ import annotations

from panopticon.schema import make_event
from panopticon.segmentizer.histogram import aggregate

OFFSET = "+10:00"


def seg(start: str, end: str, app: str = "firefox", ws: str = "1"):
    start_iso = f"2026-05-19T{start}{OFFSET}"
    end_iso = f"2026-05-19T{end}{OFFSET}"
    return make_event(
        "sway",
        "focus_segment",
        ts=start_iso,
        app_id=app,
        workspace=ws,
        start_ts=start_iso,
        end_ts=end_iso,
        duration_s=0,  # unused by aggregate; recomputed from start/end
    )


def cross_seg(start_day: str, start: str, end_day: str, end: str, app="firefox", ws="1"):
    start_iso = f"{start_day}T{start}{OFFSET}"
    end_iso = f"{end_day}T{end}{OFFSET}"
    return make_event(
        "sway", "focus_segment", ts=start_iso,
        app_id=app, workspace=ws,
        start_ts=start_iso, end_ts=end_iso, duration_s=0,
    )


def test_empty_segments_produces_zero_histogram():
    h = aggregate([], day="2026-05-19")
    assert h["day"] == "2026-05-19"
    assert h["per_app_seconds"] == {}
    assert h["per_workspace_seconds"] == {}
    assert h["per_hour_seconds"] == [0.0] * 24


def test_single_segment_attributed_to_single_hour():
    h = aggregate([seg("10:00:00.000", "10:30:00.000")], day="2026-05-19")
    assert h["per_app_seconds"] == {"firefox": 1800.0}
    assert h["per_workspace_seconds"] == {"1": 1800.0}
    assert h["per_hour_seconds"][10] == 1800.0
    assert sum(h["per_hour_seconds"]) == 1800.0


def test_segment_spanning_two_hours_splits_correctly():
    h = aggregate([seg("09:45:00.000", "10:15:00.000")], day="2026-05-19")
    assert h["per_hour_seconds"][9] == 900.0
    assert h["per_hour_seconds"][10] == 900.0
    assert sum(h["per_hour_seconds"]) == 1800.0


def test_multiple_segments_accumulate_by_app_and_workspace():
    segs = [
        seg("08:00:00.000", "08:30:00.000", app="firefox", ws="1"),
        seg("09:00:00.000", "09:15:00.000", app="ghostty", ws="2"),
        seg("10:00:00.000", "10:45:00.000", app="firefox", ws="2"),
    ]
    h = aggregate(segs, day="2026-05-19")
    assert h["per_app_seconds"] == {"firefox": 1800.0 + 2700.0, "ghostty": 900.0}
    assert h["per_workspace_seconds"] == {"1": 1800.0, "2": 900.0 + 2700.0}


def test_segment_outside_day_is_ignored():
    s = cross_seg("2026-05-17", "10:00:00.000", "2026-05-17", "11:00:00.000")
    h = aggregate([s], day="2026-05-19")
    assert h["per_app_seconds"] == {}
    assert sum(h["per_hour_seconds"]) == 0.0


def test_segment_crossing_midnight_is_clipped_to_day():
    # Segment runs 23:30 of day-1 → 00:30 of day.
    s = cross_seg("2026-05-18", "23:30:00.000", "2026-05-19", "00:30:00.000")
    h = aggregate([s], day="2026-05-19")
    # Only the 00:00–00:30 portion lands in day 2026-05-19.
    assert h["per_app_seconds"] == {"firefox": 1800.0}
    assert h["per_hour_seconds"][0] == 1800.0
    assert sum(h["per_hour_seconds"]) == 1800.0


def test_segment_crossing_into_next_day_is_clipped():
    s = cross_seg("2026-05-19", "23:30:00.000", "2026-05-20", "00:30:00.000")
    h = aggregate([s], day="2026-05-19")
    # Only the 23:30–24:00 portion counts for 2026-05-19.
    assert h["per_app_seconds"] == {"firefox": 1800.0}
    assert h["per_hour_seconds"][23] == 1800.0
