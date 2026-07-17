from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from panopticon.compositor.model import (
    DesktopObservation,
    DesktopState,
    WindowRef,
)
from panopticon.compositor.runner import Backoff, process_session, run_watcher
from panopticon.store import RawStore

FROZEN_TS = "2026-05-19T10:00:00.000+10:00"
FROZEN_DAY = "2026-05-19"


@pytest.fixture(autouse=True)
def _freeze_ts(monkeypatch):
    monkeypatch.setattr("panopticon.schema.utc_now_iso", lambda *a, **k: FROZEN_TS)


# ---- Backoff (relocated from test_sway_ipc.py, VT-5) ----


def test_backoff_yields_increasing_then_caps():
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    delays = [bo.next() for _ in range(6)]
    assert delays == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]


def test_backoff_reset_restarts_sequence():
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    bo.next()
    bo.next()
    bo.reset()
    assert bo.next() == 0.5


def test_backoff_rejects_non_positive_initial():
    with pytest.raises(ValueError, match="initial"):
        Backoff(initial=0, max_=1)


def test_backoff_rejects_max_below_initial():
    with pytest.raises(ValueError, match="max_"):
        Backoff(initial=10, max_=1)


def test_backoff_rejects_factor_le_one():
    with pytest.raises(ValueError, match="factor"):
        Backoff(initial=0.5, max_=1.0, factor=1.0)


# ---- fakes over the neutral contract ----


def _snapshot(app_id="firefox", ws="2:web", output="DP-1", title="MDN", wid=991):
    return DesktopObservation(
        event="snapshot",
        fields={
            "window_id": wid,
            "app_id": app_id,
            "pid": 1,
            "title": title,
            "workspace": ws,
            "output": output,
        },
        state=DesktopState(WindowRef(wid, app_id, 1, title), ws, output),
    )


class FakeSession:
    """A canned observation stream as one CompositorSession."""

    def __init__(self, observations: list[DesktopObservation]) -> None:
        self._observations = list(observations)

    def observations(self) -> AsyncIterator[DesktopObservation]:
        obs = self._observations

        async def gen() -> AsyncIterator[DesktopObservation]:
            for o in obs:
                yield o

        return gen()


class FakeClient:
    """Pops one queued attempt per session() call. Carries a producer."""

    producer = "sway"

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
            yield FakeSession(head)

        return cm()


def _read_lines(tmp_path) -> list[dict[str, Any]]:
    path = tmp_path / "raw" / f"desktop-{FROZEN_DAY}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---- process_session (VT-2) ----


async def test_process_session_writes_event_and_current_per_observation(tmp_path):
    observations = [
        _snapshot(),
        DesktopObservation(
            event="window_title",
            fields={"window_id": 991, "old_title": "MDN", "title": "x"},
            state=DesktopState(WindowRef(991, "firefox", 1, "x"), "2:web", "DP-1"),
        ),
    ]
    with RawStore("desktop", tmp_path) as store:
        result = await process_session(FakeSession(observations), store, "sway")
    assert result is None  # F3: no state threading / no return
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == ["snapshot", "window_title"]
    assert all(r["source"] == "desktop" and r["producer"] == "sway" for r in rows)
    assert rows[1]["old_title"] == "MDN"
    current = json.loads((tmp_path / "current" / "desktop.json").read_text())
    assert current["title"] == "x"
    assert current["window_id"] == 991


async def test_process_session_snapshot_first_then_eof(tmp_path):
    with RawStore("desktop", tmp_path) as store:
        await process_session(FakeSession([_snapshot()]), store, "sway")
    assert [r["event"] for r in _read_lines(tmp_path)] == ["snapshot"]


# ---- run_watcher (VT-2) ----


def _cancelling_sleep():
    async def fake(_: float) -> None:
        raise asyncio.CancelledError

    return fake


async def test_run_watcher_one_session_then_cancelled(tmp_path):
    client = FakeClient([[_snapshot()]])
    store = RawStore("desktop", tmp_path)
    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, sleep=_cancelling_sleep())
    finally:
        store.close()
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == ["snapshot", "compositor_disconnected"]
    assert rows[-1]["reason"] == "EOF"
    assert all(r["producer"] == "sway" for r in rows)


async def test_run_watcher_emits_reconnect_after_failure(tmp_path):
    client = FakeClient([ConnectionError("dropped"), [_snapshot()]])
    store = RawStore("desktop", tmp_path)
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, sleep=fake_sleep)
    finally:
        store.close()
    rows = _read_lines(tmp_path)
    assert [r["event"] for r in rows] == [
        "compositor_disconnected",  # initial connect failed
        "compositor_reconnected",   # second attempt succeeded
        "snapshot",                 # process_session ran
        "compositor_disconnected",  # session ended (EOF)
    ]
    assert rows[0]["reason"] == "dropped"
    assert rows[-1]["reason"] == "EOF"


async def test_run_watcher_backoff_resets_after_success(tmp_path):
    client = FakeClient([ConnectionError("a"), [_snapshot()], ConnectionError("b")])
    store = RawStore("desktop", tmp_path)
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    try:
        with pytest.raises(asyncio.CancelledError):
            await run_watcher(client, store, backoff=bo, sleep=fake_sleep)
    finally:
        store.close()
    # First disconnect → 0.5; success resets; second disconnect → 0.5 again.
    assert sleeps == [0.5, 0.5, 1.0]
