from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from panopticon.sway_watcher.ipc import (
    Backoff,
    IpcDisconnected,
    IpcEvent,
    stream,
)

# ---- Backoff ----


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


# ---- stream helpers ----


Attempt = Exception | list[IpcEvent]


def make_connect(attempts: list[Attempt]):
    """Return a connect factory that pops one attempt per invocation.

    An attempt is either an Exception to raise at connect time, or a
    list of IpcEvents to yield before the connection closes cleanly.
    """
    queue = list(attempts)

    @asynccontextmanager
    async def cm():
        if not queue:
            raise RuntimeError("no more attempts queued")
        head = queue.pop(0)
        if isinstance(head, Exception):
            raise head

        async def gen() -> AsyncIterator[IpcEvent]:
            for e in head:
                yield e

        yield gen()

    return cm


async def _collect(it, n: int) -> list[Any]:
    out: list[Any] = []
    async for msg in it:
        out.append(msg)
        if len(out) >= n:
            break
    return out


async def _noop_sleep(_: float) -> None:
    return None


# ---- stream ----


async def test_stream_emits_events_then_eof_disconnect():
    events = [IpcEvent("window", {"change": "focus"})]
    msgs = await _collect(
        stream(make_connect([events]), backoff=Backoff(initial=0.01), sleep=_noop_sleep),
        2,
    )
    assert isinstance(msgs[0], IpcEvent)
    assert msgs[0].kind == "window"
    assert isinstance(msgs[1], IpcDisconnected)
    assert msgs[1].reason == "EOF"


async def test_stream_emits_reconnected_after_initial_failure():
    msgs = await _collect(
        stream(
            make_connect([ConnectionError("dropped"), [IpcEvent("window", {})]]),
            backoff=Backoff(initial=0.01),
            sleep=_noop_sleep,
        ),
        4,
    )
    types = [type(m).__name__ for m in msgs]
    assert types == ["IpcDisconnected", "IpcReconnected", "IpcEvent", "IpcDisconnected"]
    assert isinstance(msgs[0], IpcDisconnected)
    assert msgs[0].reason == "dropped"


async def test_stream_does_not_emit_reconnected_on_very_first_connect():
    msgs = await _collect(
        stream(make_connect([[]]), backoff=Backoff(initial=0.01), sleep=_noop_sleep),
        1,
    )
    # First successful connect → straight to disconnect after EOF; no
    # spurious IpcReconnected on the very first connection.
    assert isinstance(msgs[0], IpcDisconnected)


async def test_stream_uses_backoff_delays():
    delays: list[float] = []

    async def fake_sleep(d: float) -> None:
        delays.append(d)

    attempts: list[Attempt] = [
        ConnectionError("a"),
        ConnectionError("b"),
        ConnectionError("c"),
        ConnectionError("d"),
    ]
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    msgs = await _collect(
        stream(make_connect(attempts), backoff=bo, sleep=fake_sleep),
        4,
    )
    assert all(isinstance(m, IpcDisconnected) for m in msgs)
    # The async generator pauses at the 4th yield before its own sleep
    # runs, so we only observe 3 sleep calls when collecting 4 msgs.
    assert delays == [0.5, 1.0, 2.0]


async def test_stream_backoff_resets_after_success():
    delays: list[float] = []

    async def fake_sleep(d: float) -> None:
        delays.append(d)

    attempts: list[Attempt] = [
        ConnectionError("a"),
        ConnectionError("b"),
        [IpcEvent("window", {})],  # success → resets backoff
        ConnectionError("c"),
    ]
    bo = Backoff(initial=0.5, max_=4.0, factor=2.0)
    # Collect: disc(a), disc(b), reconnect, event, disc(EOF), disc(c).
    # Sleeps run after disc(a), disc(b), disc(EOF); generator pauses
    # at disc(c) before the next sleep.
    await _collect(stream(make_connect(attempts), backoff=bo, sleep=fake_sleep), 6)
    assert delays == [0.5, 1.0, 0.5]
