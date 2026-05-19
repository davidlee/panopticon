from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from panopticon.schema import iter_jsonl, make_event
from panopticon.segmentizer.__main__ import run


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "raw").mkdir()
    return tmp_path


def write_raw(root: Path, day: str, events) -> Path:
    p = root / "raw" / f"sway-{day}.jsonl"
    p.write_text("".join(e.to_json_line() + "\n" for e in events))
    return p


def test_run_produces_segments_and_histogram_for_past_day(root: Path):
    day = "2026-05-18"
    events = [
        make_event(
            "sway", "snapshot",
            ts=f"{day}T10:00:00.000+10:00",
            app_id="firefox", workspace="1",
        ),
        make_event(
            "sway", "window_focus",
            ts=f"{day}T10:30:00.000+10:00",
            app_id="ghostty", workspace="1",
        ),
    ]
    write_raw(root, day, events)

    run(root, today=date(2026, 5, 19))

    seg_path = root / "segments" / f"focus-{day}.jsonl"
    assert seg_path.exists()
    with open(seg_path) as fh:
        segs = list(iter_jsonl(fh))
    # firefox 10:00–10:30, ghostty 10:30–next-day 00:00
    assert [s.fields["app_id"] for s in segs] == ["firefox", "ghostty"]
    assert segs[0].fields["duration_s"] == 1800.0
    # ghostty closes at next-day midnight = 13.5h
    assert segs[1].fields["duration_s"] == 13.5 * 3600

    hist_path = root / "histograms" / f"daily-{day}.json"
    assert hist_path.exists()
    h = json.loads(hist_path.read_text())
    assert h["day"] == day
    assert h["per_app_seconds"]["firefox"] == 1800.0
    assert h["per_app_seconds"]["ghostty"] == 13.5 * 3600


def test_run_with_today_does_not_extrapolate_past_last_event(root: Path):
    today = "2026-05-19"
    events = [
        make_event(
            "sway", "snapshot",
            ts=f"{today}T10:00:00.000+10:00",
            app_id="firefox", workspace="1",
        ),
        make_event(
            "sway", "window_title",
            ts=f"{today}T10:15:00.000+10:00",
            app_id="firefox", workspace="1", title="t",
        ),
    ]
    write_raw(root, today, events)

    run(root, today=date(2026, 5, 19))

    seg_path = root / "segments" / f"focus-{today}.jsonl"
    with open(seg_path) as fh:
        segs = list(iter_jsonl(fh))
    assert len(segs) == 1
    assert segs[0].fields["duration_s"] == 15 * 60.0


def test_run_skips_files_with_no_events(root: Path):
    (root / "raw" / "sway-2026-05-15.jsonl").write_text("")
    run(root, today=date(2026, 5, 19))
    assert not (root / "segments").exists() or not list(
        (root / "segments").iterdir()
    )


def test_run_handles_missing_raw_dir(tmp_path: Path):
    run(tmp_path, today=date(2026, 5, 19))  # must not raise


def test_run_invokes_retention(root: Path):
    # Old raw + matching segments → retention should remove raw, keep segments.
    old_day = "2026-04-01"
    (root / "raw" / f"sway-{old_day}.jsonl").write_text("")
    (root / "segments").mkdir()
    (root / "segments" / f"focus-{old_day}.jsonl").write_text("")
    run(root, today=date(2026, 5, 19))
    # Empty raw file produces no segments; old raw should be retained because
    # we never re-derive segments for an empty file. The pre-existing segments
    # file is what counts for retention.
    assert not (root / "raw" / f"sway-{old_day}.jsonl").exists()


def test_run_derives_browser_segments_and_merges_histogram(root: Path):
    day = "2026-05-18"
    sway_events = [
        make_event(
            "sway", "snapshot",
            ts=f"{day}T10:00:00.000+10:00",
            app_id="firefox", workspace="1",
        ),
    ]
    (root / "raw" / f"sway-{day}.jsonl").write_text(
        "".join(e.to_json_line() + "\n" for e in sway_events)
    )

    firefox_events = [
        make_event(
            "firefox", "browser_snapshot",
            ts=f"{day}T10:00:00.000+10:00",
            window_id=1, tab_id=42,
            url="https://example.com/", domain="example.com", title="ex",
        ),
        make_event(
            "firefox", "browser_navigation",
            ts=f"{day}T10:30:00.000+10:00",
            kind="committed", window_id=1, tab_id=42,
            url="https://example.com/other", domain="example.com",
        ),
    ]
    (root / "raw" / f"firefox-{day}.jsonl").write_text(
        "".join(e.to_json_line() + "\n" for e in firefox_events)
    )

    run(root, today=date(2026, 5, 19))

    browser_path = root / "segments" / f"browser-{day}.jsonl"
    assert browser_path.exists()
    with open(browser_path) as fh:
        segs = list(iter_jsonl(fh))
    assert [s.event for s in segs] == ["browser_tab_segment", "browser_tab_segment"]
    assert segs[0].fields["duration_s"] == 1800.0

    hist_path = root / "histograms" / f"daily-{day}.json"
    h = json.loads(hist_path.read_text())
    # Merged histogram carries both buckets.
    assert "per_app_seconds" in h
    assert "per_domain_seconds" in h
    assert h["per_domain_seconds"]["example.com"] > 0
