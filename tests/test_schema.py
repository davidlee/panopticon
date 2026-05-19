from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from panopticon import schema
from panopticon.schema import (
    Event,
    MalformedEventError,
    UnsupportedSchemaError,
    iter_jsonl,
    make_event,
    utc_now_iso,
)


def test_schema_version_is_one():
    assert schema.SCHEMA_VERSION == 1


def test_make_event_populates_required_fields():
    e = make_event("sway", "window_focus", app_id="firefox", con_id=991)
    assert e.v == 1
    assert e.source == "sway"
    assert e.event == "window_focus"
    assert e.fields == {"app_id": "firefox", "con_id": 991}
    assert isinstance(e.ts, str) and "T" in e.ts


def test_event_round_trips_through_json_line():
    e = make_event(
        "sway",
        "window_focus",
        ts="2026-05-19T15:42:10.531+10:00",
        app_id="firefox",
        con_id=991,
        title="MDN — Mozilla Firefox",
    )
    parsed = Event.from_json_line(e.to_json_line())
    assert parsed == e


def test_from_dict_rejects_missing_required():
    with pytest.raises(MalformedEventError, match="ts"):
        Event.from_dict({"v": 1, "source": "sway", "event": "x"})


def test_from_dict_rejects_bool_as_v():
    # Guard against ``True`` being treated as ``1`` by accident.
    with pytest.raises(MalformedEventError, match="'v' must be int"):
        Event.from_dict({"v": True, "ts": "x", "source": "sway", "event": "x"})


def test_from_dict_rejects_non_string_ts():
    with pytest.raises(MalformedEventError, match="'ts' must be str"):
        Event.from_dict({"v": 1, "ts": 123, "source": "sway", "event": "x"})


def test_from_dict_rejects_unsupported_version():
    with pytest.raises(UnsupportedSchemaError):
        Event.from_dict({"v": 2, "ts": "x", "source": "sway", "event": "x"})


def test_from_json_line_rejects_invalid_json():
    with pytest.raises(MalformedEventError, match="invalid JSON"):
        Event.from_json_line("{not json")


def test_from_json_line_rejects_non_object():
    with pytest.raises(MalformedEventError, match="must be a JSON object"):
        Event.from_json_line("[1, 2, 3]")


def test_iter_jsonl_skips_blank_malformed_and_unsupported():
    lines = [
        "",
        "   ",
        "{not json",
        json.dumps({"v": 99, "ts": "x", "source": "sway", "event": "x"}),
        json.dumps({"v": 1, "ts": "t", "source": "sway", "event": "ok"}),
        json.dumps({"v": 1, "source": "sway", "event": "missing_ts"}),
    ]
    events = list(iter_jsonl(lines))
    assert len(events) == 1
    assert events[0].event == "ok"


def test_iter_jsonl_parses_fixture():
    fixture = Path(__file__).parent / "fixtures" / "sway_events.jsonl"
    with fixture.open(encoding="utf-8") as f:
        events = list(iter_jsonl(f))
    assert [e.event for e in events] == ["window_focus", "window_title", "workspace_focus"]
    assert events[0].fields["app_id"] == "firefox"
    assert events[1].fields["old_title"].startswith("New Tab")
    assert events[2].fields["workspace"] == "2:web"


def test_utc_now_iso_uses_provided_time_with_offset():
    tz = timezone(timedelta(hours=10))
    when = datetime(2026, 5, 19, 15, 42, 10, 531000, tzinfo=tz)
    s = utc_now_iso(when)
    assert s == "2026-05-19T15:42:10.531+10:00"


def test_utc_now_iso_default_has_offset():
    # Default path: must include a timezone offset (never naive).
    s = utc_now_iso()
    # Either "+HH:MM"/"-HH:MM" tail or "Z"-equivalent.
    assert s.endswith("Z") or s[-6] in "+-"
