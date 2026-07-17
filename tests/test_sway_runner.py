from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from panopticon.compositor.runner import Backoff
from panopticon.compositor.sway.project import IpcEvent
from panopticon.store import RawStore
from panopticon.sway_watcher.runner import (
    process_session,
    run_watcher,
)
from panopticon.sway_watcher.state import FocusState

FROZEN_TS = "2026-05-19T10:00:00.000+10:00"
FROZEN_DAY = "2026-05-19"


@pytest.fixture(autouse=True)
def _freeze_ts(monkeypatch):
    """All make_event() calls in the run use the same ts → same day → same file."""
    monkeypatch.setattr("panopticon.schema.utc_now_iso", lambda *a, **k: FROZEN_TS)


def _tree(focused_app_id: str = "firefox", title: str = "MDN") -> dict[str, Any]:
    return {
        "id": 1,
        "type": "root",
        "focused": False,
        "nodes": [
            {
                "id": 2,
                "type": "output",
                "name": "DP-1",
                "focused": False,
                "nodes": [
                    {
                        "id": 3,
                        "type": "workspace",
                        "name": "2:web",
                        "focused": True,
                        "nodes": [
                            {
                                "id": 991,
                                "type": "con",
                                "app_id": focused_app_id,
                                "pid": 12345,
                                "name": title,
                                "focused": True,
                            }
                        ],
                        "floating_nodes": [],
                    }
                ],
                "floating_nodes": [],
            }
        ],
        "floating_nodes": [],
    }


class FakeSession:
    """A canned (tree, events) pair as one IPC session."""

    def __init__(self, tree: dict[str, Any], events: list[IpcEvent]) -> None:
        self._tree = tree
        self._events = list(events)

    def events(self) -> AsyncIterator[IpcEvent]:
        events = self._events

        async def gen() -> AsyncIterator[IpcEvent]:
            for e in events:
                yield e

        return gen()

    async def get_tree(self) -> dict[str, Any]:
        return self._tree


class FakeClient:
    """Pops one queued attempt per session() call."""

    Attempt = "tuple[dict, list[IpcEvent]] | Exception"

    def __init__(self, attempts: list) -> None:
        self._attempts = list(attempts)

    def session(self):
        attempts = self._attempts

        @asynccontextmanager
        async def cm():
            if not attempts:
                raise RuntimeError("no more attempts queued")
            head = attempts.pop(0)
            if isinstance(head, Exception):
                raise head
            tree, events = head
            yield FakeSession(tree, events)

        return cm()


def _read_lines(tmp_path) -> list[dict[str, Any]]:
    path = tmp_path / "raw" / f"sway-{FROZEN_DAY}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---- process_session ----


async def test_process_session_writes_snapshot_and_event(tmp_path):
    tree = _tree()
    events = [
        IpcEvent(
            "window",
            {"change": "title", "container": {"id": 991, "name": "Sway IPC — Firefox"}},
        )
    ]
    with RawStore("sway", tmp_path) as store:
        state = await process_session(FakeSession(tree, events), store, FocusState())
    assert state.title == "Sway IPC — Firefox"
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == ["snapshot", "window_title"]
    assert rows[0]["app_id"] == "firefox"
    assert rows[1]["old_title"] == "MDN"
    assert rows[1]["title"] == "Sway IPC — Firefox"


async def test_process_session_updates_current_state(tmp_path):
    tree = _tree()
    events = [
        IpcEvent("window", {"change": "title", "container": {"id": 991, "name": "x"}})
    ]
    with RawStore("sway", tmp_path) as store:
        await process_session(FakeSession(tree, events), store, FocusState())
    snapshot = json.loads((tmp_path / "current" / "sway.json").read_text())
    assert snapshot["title"] == "x"
    assert snapshot["app_id"] == "firefox"


async def test_process_session_handles_no_events(tmp_path):
    with RawStore("sway", tmp_path) as store:
        state = await process_session(FakeSession(_tree(), []), store, FocusState())
    assert state.app_id == "firefox"
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == ["snapshot"]


# ---- run_watcher ----


def _cancelling_sleep():
    """A sleep coroutine that cancels the task the first time it's awaited."""

    async def fake(_: float) -> None:
        raise asyncio.CancelledError

    return fake


async def test_run_watcher_one_session_then_cancelled(tmp_path):
    tree = _tree()
    events = [
        IpcEvent("window", {"change": "title", "container": {"id": 991, "name": "z"}})
    ]
    client = FakeClient([(tree, events)])
    store = RawStore("sway", tmp_path)
    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, sleep=_cancelling_sleep())
    finally:
        store.close()
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == [
        "snapshot",
        "window_title",
        "sway_disconnected",
    ]
    assert rows[-1]["reason"] == "EOF"


async def test_run_watcher_emits_reconnect_after_failure(tmp_path):
    """Initial connect fails; second succeeds → disc, reconnect, snapshot."""
    tree = _tree()
    client = FakeClient([ConnectionError("dropped"), (tree, [])])
    store = RawStore("sway", tmp_path)

    sleeps: list[float] = []
    cancel_after = 2

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)
        if len(sleeps) >= cancel_after:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, sleep=fake_sleep)
    finally:
        store.close()

    rows = _read_lines(tmp_path)
    names = [r["event"] for r in rows]
    assert names == [
        "sway_disconnected",  # initial connect failed
        "sway_reconnected",   # second attempt succeeded
        "snapshot",           # process_session ran
        "sway_disconnected",  # session ended (EOF)
    ]
    assert rows[0]["reason"] == "dropped"
    assert rows[-1]["reason"] == "EOF"


async def test_run_watcher_backoff_resets_after_success(tmp_path):
    """A successful session resets backoff so the next failure starts at initial."""
    tree = _tree()
    client = FakeClient([
        ConnectionError("a"),
        (tree, []),
        ConnectionError("b"),
    ])
    store = RawStore("sway", tmp_path)
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    sleeps: list[float] = []
    cancel_after = 3

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)
        if len(sleeps) >= cancel_after:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, backoff=bo, sleep=fake_sleep)
    finally:
        store.close()

    # First disconnect → 0.5; success resets; second disconnect → 0.5 again.
    assert sleeps == [0.5, 0.5, 1.0]
