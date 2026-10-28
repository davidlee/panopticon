"""IMP-006: typing per window, aggregated from keyrate window rows into the daily histogram."""

from __future__ import annotations

from panopticon.schema import make_event
from panopticon.segmentizer.histogram import aggregate_typing


def window(minute: str, app: str, title: str | None, keys: int, key_seconds: int):
    return make_event(
        "keyrate", "keyrate_window", ts=f"2026-10-28T{minute}:00.000+11:00",
        app_id=app, title=title, keys=keys, key_seconds=key_seconds,
    )  # fmt: skip


def test_typing_is_summed_per_app_and_title_with_the_rate_while_typing():
    rows = [
        window("09:00", "emacs", "notes.org", 120, 40),
        window("09:01", "emacs", "notes.org", 60, 20),
        window("09:01", "emacs", "*scratch*", 10, 5),
        window("09:02", "firefox", None, 6, 3),
        make_event("keyrate", "keyrate_minute", ts="2026-10-28T09:00:00.000+11:00", keys=999),
    ]
    assert aggregate_typing(rows) == {
        "typing_per_app": {
            "emacs": {
                "keys": 190, "key_seconds": 65, "wpm": 35.1,
                "titles": {
                    "notes.org": {"keys": 180, "key_seconds": 60, "wpm": 36.0},
                    "*scratch*": {"keys": 10, "key_seconds": 5, "wpm": 24.0},
                },
            },
            "firefox": {
                "keys": 6, "key_seconds": 3, "wpm": 24.0,
                "titles": {"(untitled)": {"keys": 6, "key_seconds": 3, "wpm": 24.0}},
            },
        }
    }  # fmt: skip


def test_no_window_rows_is_no_typing():
    assert aggregate_typing([]) == {"typing_per_app": {}}
