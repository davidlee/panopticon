"""IMP-005: keyrate wire formats — the raw event, the legacy SATAN TSV, the live line."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from panopticon.keyrate.count import MinuteRow, Snapshot, WindowRow
from panopticon.keyrate.render import legacy_tsv, minute_event, snapshot_line, window_events
from panopticon.schema import Event

T0 = 1_800_000_000
START = datetime(2027, 1, 15, 18, 0, tzinfo=timezone(timedelta(hours=11)))
ROW = MinuteRow(start=T0, keys=187, key_seconds=41, pointer_seconds=12, peak_5s_cpm=432)


def test_minute_event_round_trips_through_the_schema():
    line = minute_event(ROW, START).to_json_line()
    assert Event.from_json_line(line).to_dict() == {
        "v": 1,
        "ts": "2027-01-15T18:00:00.000+11:00",
        "source": "keyrate",
        "event": "keyrate_minute",
        "keys": 187,
        "key_seconds": 41,
        "pointer_seconds": 12,
        "peak_5s_cpm": 432,
    }


def test_legacy_tsv_matches_the_wpm_daemon_columns():
    # <iso8601_local> <keys> <peak_5s_wpm> <active_seconds>, one file per local day
    assert legacy_tsv(ROW, START) == ("2027-01-15", "2027-01-15T18:00:00\t187\t86\t41\n")


def test_legacy_tsv_skips_minutes_without_keys():
    pointer_only = MinuteRow(start=T0, keys=0, key_seconds=0, pointer_seconds=30, peak_5s_cpm=0)
    assert legacy_tsv(pointer_only, START) is None


def test_snapshot_line_is_one_json_object_per_line():
    line = snapshot_line(Snapshot(cpm_5s=360, cpm_60s=212, pointer_seconds_60s=7), devices=3)
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == {
        "cpm_5s": 360,
        "cpm_60s": 212,
        "pointer_seconds_60s": 7,
        "devices": 3,
    }


def test_each_window_of_a_minute_is_its_own_event():
    row = MinuteRow(
        start=T0, keys=9, key_seconds=5, pointer_seconds=0, peak_5s_cpm=60,
        windows=(WindowRow("emacs", "notes.org", 7, 4), WindowRow("firefox", None, 2, 1)),
    )  # fmt: skip
    assert [e.to_dict() for e in window_events(row, START)] == [
        {
            "v": 1,
            "ts": "2027-01-15T18:00:00.000+11:00",
            "source": "keyrate",
            "event": "keyrate_window",
            "app_id": "emacs",
            "title": "notes.org",
            "keys": 7,
            "key_seconds": 4,
        },
        {
            "v": 1,
            "ts": "2027-01-15T18:00:00.000+11:00",
            "source": "keyrate",
            "event": "keyrate_window",
            "app_id": "firefox",
            "title": None,
            "keys": 2,
            "key_seconds": 1,
        },
    ]
