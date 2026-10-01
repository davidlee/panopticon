"""Tests for candidate selection over the content index (design §5.4 Selection, D5)."""

from __future__ import annotations

from typing import Any

import pytest

from panopticon.digest.gate import DEFAULT_DENY, GateConfig, Pass, Reason, Reject
from panopticon.digest.select import Judged, pending

CFG = GateConfig(deny=DEFAULT_DENY | {"bank.com"}, allow=None, min_chars=1500, min_quality=0.7)


def row(sha: str, url: str, at: str, quality: Any = 1.0, **extra: Any) -> dict[str, Any]:
    return {
        "content_hash": sha,
        "url": url,
        "domain": extra.pop("domain", "unused.example"),
        "title": "t",
        "captured_at": at,
        "quality_score": quality,
        **extra,
    }


def verdicts(judged: list[Judged]) -> list[tuple[str, Any]]:
    return [(j.row["content_hash"], j.verdict) for j in judged]


def test_latest_sha_per_url_wins_across_mixed_offsets_and_z():
    # 10:00+10:00 is 00:00Z: lexically later, chronologically earlier than 01:00Z
    rows = [
        row("a", "https://example.org/p", "2026-01-01T10:00:00+10:00"),
        row("b", "https://example.org/p", "2026-01-01T01:00:00Z"),
        row("c", "https://example.org/p", "2026-01-01T00:30:00.123456+00:00"),
    ]
    assert verdicts(pending(rows, set(), CFG)) == [
        ("b", Pass("example.org")),
        ("c", Reject(Reason.SUPERSEDED)),
        ("a", Reject(Reason.SUPERSEDED)),
    ]


def test_done_latest_is_done_and_does_not_fall_back():
    rows = [
        row("old", "https://example.org/p", "2026-01-01T00:00:00Z"),
        row("new", "https://example.org/p", "2026-01-02T00:00:00Z"),
    ]
    assert verdicts(pending(rows, {"new"}, CFG)) == [
        ("new", Reject(Reason.DONE)),
        ("old", Reject(Reason.SUPERSEDED)),
    ]


def test_gated_latest_does_not_fall_back():
    rows = [
        row("good", "https://example.org/p", "2026-01-01T00:00:00Z", quality=1.0),
        row("poor", "https://example.org/p", "2026-01-02T00:00:00Z", quality=0.1),
    ]
    assert verdicts(pending(rows, set(), CFG)) == [
        ("poor", Reject(Reason.LOW_QUALITY)),
        ("good", Reject(Reason.SUPERSEDED)),
    ]


def test_orders_newest_first_across_urls():
    rows = [
        row("x", "https://x.example/", "2026-01-01T00:00:00Z"),
        row("z", "https://z.example/", "2026-01-03T00:00:00+05:00"),
        row("y", "https://y.example/", "2026-01-02T00:00:00Z"),
    ]
    assert [sha for sha, _ in verdicts(pending(rows, set(), CFG))] == ["z", "y", "x"]


def test_host_comes_from_the_url_never_the_stored_domain():
    rows = [
        row("a", "https://example.org/", "2026-01-01T00:00:00Z", domain="bank.com"),
        row("b", "https://bank.com/", "2026-01-01T00:00:00Z", domain="example.org"),
    ]
    got = dict(verdicts(pending(rows, set(), CFG)))
    assert got == {"a": Pass("example.org"), "b": Reject(Reason.DENIED_DOMAIN)}


def test_too_short_is_left_to_the_shell():
    # pending has no page length; too_short needs the .json
    rows = [row("a", "https://example.org/", "2026-01-01T00:00:00Z")]
    assert verdicts(pending(rows, set(), CFG)) == [("a", Pass("example.org"))]


def test_same_instant_prefers_the_later_index_row():
    rows = [
        row("first", "https://example.org/", "2026-01-01T00:00:00Z"),
        row("second", "https://example.org/", "2026-01-01T10:00:00+10:00"),
    ]
    assert dict(verdicts(pending(rows, set(), CFG))) == {
        "second": Pass("example.org"),
        "first": Reject(Reason.SUPERSEDED),
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"captured_at": "2026-01-01T00:00:00"},  # naive
        {"captured_at": "yesterday"},
        {"captured_at": None},
        {"url": None},
        {"content_hash": 7},
        {"quality_score": "high"},
        {"quality_score": True},
        {"quality_score": None},
    ],
)
def test_malformed_rows_are_bad_row_and_sort_last(bad: dict[str, Any]):
    rows = [
        row("ok", "https://example.org/", "2026-01-01T00:00:00Z"),
        {**row("bad", "https://example.net/", "2026-01-02T00:00:00Z"), **bad},
    ]
    assert verdicts(pending(rows, set(), CFG)) == [
        ("ok", Pass("example.org")),
        (bad.get("content_hash", "bad"), Reject(Reason.BAD_ROW)),
    ]


def test_a_bad_row_never_supersedes_a_good_one():
    rows = [
        row("ok", "https://example.org/", "2026-01-01T00:00:00Z"),
        {**row("bad", "https://example.org/", "2026-01-02T00:00:00Z"), "quality_score": None},
    ]
    assert dict(verdicts(pending(rows, set(), CFG)))["ok"] == Pass("example.org")


def test_empty_index():
    assert pending([], set(), CFG) == []
