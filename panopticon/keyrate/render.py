"""Pure keyrate wire formats: the raw minute and window events, the legacy SATAN TSV, the live line.

``start`` is the row's minute start as an aware local datetime; the shell
converts the epoch so this module needs no clock or timezone database.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime

from panopticon.keyrate.count import MinuteRow, Snapshot
from panopticon.schema import Event, make_event, utc_now_iso

SOURCE = "keyrate"
CHARS_PER_WORD = 5


def minute_event(row: MinuteRow, start: datetime) -> Event:
    return make_event(
        SOURCE,
        "keyrate_minute",
        ts=utc_now_iso(start),
        keys=row.keys,
        key_seconds=row.key_seconds,
        pointer_seconds=row.pointer_seconds,
        peak_5s_cpm=row.peak_5s_cpm,
    )


def window_events(row: MinuteRow, start: datetime) -> list[Event]:
    """One ``keyrate_window`` event per window the minute's keys landed in."""
    return [
        make_event(
            SOURCE,
            "keyrate_window",
            ts=utc_now_iso(start),
            app_id=w.app_id,
            title=w.title,
            keys=w.keys,
            key_seconds=w.key_seconds,
        )
        for w in row.windows
    ]


def legacy_tsv(row: MinuteRow, start: datetime) -> tuple[str, str] | None:
    """``(day, line)`` in the retired wpm-daemon's format, or ``None`` for a keyless minute.

    Columns: ``<iso8601_local> <keys> <peak_5s_wpm> <active_seconds>``; one file
    per local day. SATAN's WPM sensor reads these until it moves to the raw stream.
    """
    if not row.keys:
        return None
    stamp = start.replace(tzinfo=None).isoformat(timespec="seconds")
    peak_wpm = round(row.peak_5s_cpm / CHARS_PER_WORD)
    return start.date().isoformat(), f"{stamp}\t{row.keys}\t{peak_wpm}\t{row.key_seconds}\n"


def snapshot_line(snapshot: Snapshot, devices: int) -> str:
    payload = {**dataclasses.asdict(snapshot), "devices": devices}
    return json.dumps(payload, separators=(",", ":")) + "\n"
