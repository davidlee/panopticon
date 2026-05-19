from __future__ import annotations

import json
from pathlib import Path

from panopticon.schema import make_event
from panopticon.store import RawStore, state_dir


def test_state_dir_uses_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert state_dir() == tmp_path / "state" / "behaviour"


def test_state_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/some/home")
    assert state_dir() == Path("/some/home/.local/state/behaviour")


def test_write_creates_per_day_file(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write(make_event("sway", "snapshot", ts="2026-05-19T15:42:10.531+10:00"))
    expected = tmp_path / "raw" / "sway-2026-05-19.jsonl"
    assert expected.exists()
    lines = expected.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "snapshot"


def test_write_appends_within_same_day(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write(make_event("sway", "a", ts="2026-05-19T08:00:00.000+10:00"))
        store.write(make_event("sway", "b", ts="2026-05-19T09:00:00.000+10:00"))
    text = (tmp_path / "raw" / "sway-2026-05-19.jsonl").read_text()
    assert [json.loads(line)["event"] for line in text.splitlines()] == ["a", "b"]


def test_write_rotates_on_day_change(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write(make_event("sway", "a", ts="2026-05-19T23:59:59.000+10:00"))
        store.write(make_event("sway", "b", ts="2026-05-20T00:00:01.000+10:00"))
    assert (tmp_path / "raw" / "sway-2026-05-19.jsonl").exists()
    assert (tmp_path / "raw" / "sway-2026-05-20.jsonl").exists()


def test_reopen_preserves_existing(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write(make_event("sway", "a", ts="2026-05-19T08:00:00.000+10:00"))
    with RawStore("sway", tmp_path) as store:
        store.write(make_event("sway", "b", ts="2026-05-19T09:00:00.000+10:00"))
    text = (tmp_path / "raw" / "sway-2026-05-19.jsonl").read_text()
    assert [json.loads(line)["event"] for line in text.splitlines()] == ["a", "b"]


def test_write_current_atomic_snapshot(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write_current({"focused_app_id": "firefox", "title": "MDN"})
    target = tmp_path / "current" / "sway.json"
    assert json.loads(target.read_text()) == {"focused_app_id": "firefox", "title": "MDN"}


def test_write_current_replaces_existing(tmp_path):
    with RawStore("sway", tmp_path) as store:
        store.write_current({"a": 1})
        store.write_current({"a": 2})
    target = tmp_path / "current" / "sway.json"
    assert json.loads(target.read_text()) == {"a": 2}


def test_close_idempotent(tmp_path):
    store = RawStore("sway", tmp_path)
    store.write(make_event("sway", "a", ts="2026-05-19T08:00:00.000+10:00"))
    store.close()
    store.close()  # must not raise


def test_path_for_uses_source_and_day(tmp_path):
    store = RawStore("firefox", tmp_path)
    assert store.path_for("2026-05-19") == tmp_path / "raw" / "firefox-2026-05-19.jsonl"
