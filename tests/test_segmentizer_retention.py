from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from panopticon.segmentizer.retention import enforce


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "raw").mkdir()
    (tmp_path / "segments").mkdir()
    (tmp_path / "histograms").mkdir()
    return tmp_path


def touch(p: Path) -> Path:
    p.write_text("")
    return p


def test_empty_root_returns_empty_report(root: Path):
    r = enforce(root, now=date(2026, 5, 19))
    assert r.removed_raw == []
    assert r.skipped_raw_unsegmented == []
    assert r.removed_segments == []


def test_raw_within_retention_is_kept(root: Path):
    p = touch(root / "raw" / "desktop-2026-05-15.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert p.exists()
    assert r.removed_raw == []


def test_raw_past_retention_with_segments_is_deleted(root: Path):
    p = touch(root / "raw" / "desktop-2026-05-01.jsonl")
    touch(root / "segments" / "focus-2026-05-01.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert not p.exists()
    assert r.removed_raw == [p]
    assert r.skipped_raw_unsegmented == []


def test_raw_past_retention_without_segments_is_skipped(root: Path):
    p = touch(root / "raw" / "desktop-2026-05-01.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert p.exists()
    assert r.removed_raw == []
    assert r.skipped_raw_unsegmented == [p]


def test_segments_past_retention_are_deleted(root: Path):
    old = touch(root / "segments" / "focus-2025-01-01.jsonl")
    fresh = touch(root / "segments" / "focus-2026-05-15.jsonl")
    r = enforce(root, now=date(2026, 5, 19), segment_days=90)
    assert not old.exists()
    assert fresh.exists()
    assert r.removed_segments == [old]


def test_histograms_never_deleted(root: Path):
    p = touch(root / "histograms" / "daily-2020-01-01.json")
    enforce(root, now=date(2026, 5, 19))
    assert p.exists()


def test_unparseable_filenames_are_ignored(root: Path):
    junk = touch(root / "raw" / "random.txt")
    enforce(root, now=date(2026, 5, 19))
    assert junk.exists()


def test_firefox_raw_requires_browser_segments(root: Path):
    p = touch(root / "raw" / "firefox-2026-05-01.jsonl")
    # A focus segment for the same day is not enough: firefox raw must
    # have a *browser-*.jsonl* segment to be safe to delete.
    touch(root / "segments" / "focus-2026-05-01.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert p.exists()
    assert r.skipped_raw_unsegmented == [p]


def test_firefox_raw_with_browser_segments_is_deleted(root: Path):
    p = touch(root / "raw" / "firefox-2026-05-01.jsonl")
    touch(root / "segments" / "browser-2026-05-01.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert not p.exists()
    assert r.removed_raw == [p]


def test_desktop_raw_requires_focus_not_browser_segments(root: Path):
    p = touch(root / "raw" / "desktop-2026-05-01.jsonl")
    touch(root / "segments" / "browser-2026-05-01.jsonl")
    r = enforce(root, now=date(2026, 5, 19), raw_days=7)
    assert p.exists()
    assert r.skipped_raw_unsegmented == [p]
