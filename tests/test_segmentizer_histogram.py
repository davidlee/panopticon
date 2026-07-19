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


# --- R4: per-output workspace de-conflation (niri carries `output`) -----------


def seg_out(start: str, end: str, output: str, app: str = "firefox", ws: str = "1"):
    """A focus_segment carrying an ``output`` (niri shape)."""
    start_iso = f"2026-05-19T{start}{OFFSET}"
    end_iso = f"2026-05-19T{end}{OFFSET}"
    return make_event(
        "niri", "focus_segment", ts=start_iso,
        app_id=app, workspace=ws, output=output,
        start_ts=start_iso, end_ts=end_iso, duration_s=0,
    )


def test_same_workspace_idx_on_different_outputs_does_not_conflate():
    segs = [
        seg_out("08:00:00.000", "08:30:00.000", output="DP-3", ws="1"),
        seg_out("09:00:00.000", "09:15:00.000", output="eDP-1", ws="1"),
    ]
    h = aggregate(segs, day="2026-05-19")
    # Keyed by output/workspace — the two ws "1"s stay distinct (D8).
    assert h["per_workspace_seconds"] == {"DP-3/1": 1800.0, "eDP-1/1": 900.0}


def test_segment_without_output_keeps_bare_workspace_key():
    # Legacy sway segments omit `output` → byte-identical bare-key aggregation.
    h = aggregate([seg("10:00:00.000", "10:30:00.000", ws="1")], day="2026-05-19")
    assert h["per_workspace_seconds"] == {"1": 1800.0}


def test_output_keying_leaves_per_app_and_per_hour_unchanged():
    h = aggregate(
        [seg_out("10:00:00.000", "10:30:00.000", output="DP-3", app="ghostty", ws="2")],
        day="2026-05-19",
    )
    assert h["per_app_seconds"] == {"ghostty": 1800.0}  # per_app never keyed on output
    assert h["per_hour_seconds"][10] == 1800.0
    assert h["per_workspace_seconds"] == {"DP-3/2": 1800.0}
