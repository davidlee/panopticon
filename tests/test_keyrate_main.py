"""IMP-005: the keyrate tick — closed minutes reach the raw store and the legacy TSV."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from panopticon.keyrate.__main__ import CurrentWindow, Outputs, parse_args, tick
from panopticon.keyrate.count import Activity, Counter
from panopticon.schema import iter_jsonl
from panopticon.store import RawStore

T0 = 1_800_000_000  # 2027-01-15T08:00:00Z


class FakeHub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def broadcast(self, line: str) -> None:
        self.lines.append(line)


@pytest.fixture(autouse=True)
def plus_eleven(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TZ", "UTC-11")  # POSIX: eleven hours *ahead* of UTC
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def outputs(tmp_path: Path):
    with RawStore("keyrate", tmp_path / "state") as store:
        yield Outputs(store=store, legacy_dir=tmp_path / "wpm", hub=FakeHub())


def _typed(counter: Counter, *times: float) -> Counter:
    for t in times:
        counter.record(Activity.KEY, t)
    return counter


def test_a_closed_minute_is_written_to_both_logs(outputs: Outputs, tmp_path: Path):
    counter = _typed(Counter(T0), T0 + 1, T0 + 2, T0 + 2.5)
    tick(counter, T0 + 59, outputs, devices=2)
    assert not (tmp_path / "state" / "raw").exists()

    tick(counter, T0 + 60, outputs, devices=2)

    raw = (tmp_path / "state" / "raw" / "keyrate-2027-01-15.jsonl").read_text()
    [event] = list(iter_jsonl(raw.splitlines()))
    assert (event.ts, event.fields["keys"]) == ("2027-01-15T19:00:00.000+11:00", 3)
    legacy = (tmp_path / "wpm" / "2027-01-15.tsv").read_text()
    assert legacy == "2027-01-15T19:00:00\t3\t7\t2\n"


def test_window_rows_follow_their_minute(outputs: Outputs, tmp_path: Path):
    counter = Counter(T0)
    counter.record(Activity.KEY, T0 + 1, ("emacs", "notes.org"))
    tick(counter, T0 + 60, outputs, devices=1)

    raw = (tmp_path / "state" / "raw" / "keyrate-2027-01-15.jsonl").read_text()
    minute, window = iter_jsonl(raw.splitlines())
    assert (minute.event, window.event) == ("keyrate_minute", "keyrate_window")
    assert (window.ts, window.fields["app_id"], window.fields["keys"]) == (minute.ts, "emacs", 1)


def test_legacy_rows_append(outputs: Outputs, tmp_path: Path):
    counter = _typed(Counter(T0), T0 + 1, T0 + 61)
    tick(counter, T0 + 60, outputs, devices=1)
    tick(counter, T0 + 120, outputs, devices=1)
    assert len((tmp_path / "wpm" / "2027-01-15.tsv").read_text().splitlines()) == 2


def test_no_legacy_dir_writes_only_the_raw_stream(tmp_path: Path):
    with RawStore("keyrate", tmp_path / "state") as store:
        out = Outputs(store=store, legacy_dir=None, hub=FakeHub())
        tick(_typed(Counter(T0), T0 + 1), T0 + 60, out, devices=1)
    assert (tmp_path / "state" / "raw" / "keyrate-2027-01-15.jsonl").exists()
    assert not (tmp_path / "wpm").exists()


def test_every_tick_broadcasts_the_live_rate(outputs: Outputs):
    counter = _typed(Counter(T0), T0 + 1, T0 + 2)
    tick(counter, T0 + 3, outputs, devices=2)
    tick(counter, T0 + 4, outputs, devices=2)
    assert [json.loads(line) for line in outputs.hub.lines] == [
        {"cpm_5s": 24, "cpm_60s": 2, "pointer_seconds_60s": 0, "devices": 2},
    ] * 2


def test_legacy_dir_defaults_under_satan_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert parse_args([]).legacy_dir == tmp_path / "satan" / "log" / "wpm"
    assert parse_args(["--no-legacy"]).legacy_dir is None


def _focus(store: RawStore, app_id: str | None, title: str | None) -> None:
    store.write_current({"window_id": "w", "app_id": app_id, "title": title})


def test_current_window_follows_the_desktop_watcher(tmp_path: Path):
    with RawStore("desktop", tmp_path) as desktop:
        current = CurrentWindow(desktop.current_path)
        assert current() is None  # no watcher yet

        _focus(desktop, "emacs", "notes.org")
        assert current() == ("emacs", "notes.org")
        _focus(desktop, "com.mitchellh.ghostty", "◐ Claude Code")
        assert current() == ("com.mitchellh.ghostty", "Claude Code")
        _focus(desktop, None, None)  # disconnected
        assert current() is None


def test_an_unreadable_current_state_is_no_window(tmp_path: Path):
    path = tmp_path / "current" / "desktop.json"
    path.parent.mkdir()
    path.write_text("{trunc")
    assert CurrentWindow(path)() is None
