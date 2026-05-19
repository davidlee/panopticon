from __future__ import annotations

from panopticon.schema import make_event
from panopticon.segmentizer.histogram import aggregate, aggregate_browser

OFFSET = "+10:00"


def bseg(start: str, end: str, *, domain: str = "example.com", tab_id: int = 1):
    start_iso = f"2026-05-19T{start}{OFFSET}"
    end_iso = f"2026-05-19T{end}{OFFSET}"
    return make_event(
        "firefox",
        "browser_tab_segment",
        ts=start_iso,
        start_ts=start_iso,
        end_ts=end_iso,
        duration_s=0,
        window_id=1,
        tab_id=tab_id,
        url=f"https://{domain}/",
        domain=domain,
        title_start=domain,
        title_end=domain,
        audible=False,
    )


def fseg(start: str, end: str, app: str = "firefox", ws: str = "1"):
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
        duration_s=0,
    )


def test_empty_browser_histogram():
    h = aggregate_browser([], day="2026-05-19")
    assert h["day"] == "2026-05-19"
    assert h["per_domain_seconds"] == {}
    assert h["per_browser_hour_seconds"] == [0.0] * 24


def test_browser_segment_attributed_to_domain():
    h = aggregate_browser(
        [bseg("10:00:00.000", "10:30:00.000", domain="example.com")],
        day="2026-05-19",
    )
    assert h["per_domain_seconds"] == {"example.com": 1800.0}
    assert h["per_browser_hour_seconds"][10] == 1800.0


def test_browser_segments_accumulate_per_domain():
    segs = [
        bseg("08:00:00.000", "08:30:00.000", domain="a.example"),
        bseg("09:00:00.000", "09:15:00.000", domain="b.example"),
        bseg("10:00:00.000", "10:45:00.000", domain="a.example"),
    ]
    h = aggregate_browser(segs, day="2026-05-19")
    assert h["per_domain_seconds"] == {
        "a.example": 1800.0 + 2700.0,
        "b.example": 900.0,
    }


def test_missing_domain_falls_back_to_unknown():
    seg = make_event(
        "firefox",
        "browser_tab_segment",
        ts="2026-05-19T10:00:00.000+10:00",
        start_ts="2026-05-19T10:00:00.000+10:00",
        end_ts="2026-05-19T10:30:00.000+10:00",
        duration_s=0,
    )
    h = aggregate_browser([seg], day="2026-05-19")
    assert h["per_domain_seconds"] == {"(unknown)": 1800.0}


def test_browser_aggregate_ignores_focus_segments():
    h = aggregate_browser(
        [fseg("10:00:00.000", "10:30:00.000")],
        day="2026-05-19",
    )
    assert h["per_domain_seconds"] == {}


def test_focus_aggregate_ignores_browser_segments():
    h = aggregate(
        [bseg("10:00:00.000", "10:30:00.000")],
        day="2026-05-19",
    )
    assert h["per_app_seconds"] == {}
    assert sum(h["per_hour_seconds"]) == 0.0


def test_browser_segment_crossing_midnight_clipped():
    start = "2026-05-18T23:30:00.000+10:00"
    end = "2026-05-19T00:30:00.000+10:00"
    seg = make_event(
        "firefox",
        "browser_tab_segment",
        ts=start,
        start_ts=start,
        end_ts=end,
        duration_s=0,
        url="https://a.example/",
        domain="a.example",
    )
    h = aggregate_browser([seg], day="2026-05-19")
    assert h["per_domain_seconds"] == {"a.example": 1800.0}
    assert h["per_browser_hour_seconds"][0] == 1800.0
