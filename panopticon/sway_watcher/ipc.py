"""IPC stream primitives: backoff + reconnect-aware async iterator.

The :func:`stream` async generator turns a *connect factory* into an
infinite stream of :data:`StreamMessage`\\ s.  It owns the
reconnect-with-backoff loop so the watcher's main loop is a flat
``async for``.

i3ipc-python integration lives in the watcher's ``__main__`` adapter
where the real :class:`i3ipc.aio.Connection` plugs into ``connect``.
Tests use a fake factory so the retry semantics can be exercised
without a running compositor.
"""

from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
)
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Backoff",
    "IpcDisconnected",
    "IpcEvent",
    "IpcReconnected",
    "StreamMessage",
    "stream",
]


@dataclass(frozen=True, slots=True)
class IpcEvent:
    """One IPC event from the compositor."""

    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IpcDisconnected:
    """The IPC connection failed or closed; reconnect attempt scheduled."""

    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IpcReconnected:
    """A fresh IPC connection has been established after a prior drop."""


StreamMessage = IpcEvent | IpcDisconnected | IpcReconnected


class Backoff:
    """Exponential backoff with an upper bound. Deterministic; no jitter."""

    def __init__(
        self,
        *,
        initial: float = 0.5,
        max_: float = 30.0,
        factor: float = 2.0,
    ) -> None:
        if initial <= 0:
            raise ValueError("initial must be > 0")
        if max_ < initial:
            raise ValueError("max_ must be >= initial")
        if factor <= 1:
            raise ValueError("factor must be > 1")
        self._initial = initial
        self._max = max_
        self._factor = factor
        self._next = initial

    def next(self) -> float:
        """Return the next delay and advance the sequence."""
        delay = self._next
        self._next = min(self._next * self._factor, self._max)
        return delay

    def reset(self) -> None:
        self._next = self._initial


ConnectFactory = Callable[[], AbstractAsyncContextManager[AsyncIterable[IpcEvent]]]


async def stream(
    connect: ConnectFactory,
    *,
    backoff: Backoff | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[StreamMessage]:
    """Drive an IPC connection with reconnect-with-backoff semantics.

    ``connect`` is a no-arg factory that returns a fresh async context
    manager.  Entering the context manager opens the connection and
    yields an :class:`AsyncIterable` of :class:`IpcEvent`; exiting it
    cleans up.

    The stream yields:

    * :class:`IpcEvent` for each event seen.
    * :class:`IpcDisconnected` after the connection drops (clean EOF
      or exception); ``reason`` carries the exception's string form
      or ``"EOF"`` for a clean close.
    * :class:`IpcReconnected` immediately after a non-first
      connection succeeds, so consumers can emit the matching
      ``sway_reconnected`` event.

    Backoff is reset on each successful connect and advanced on each
    failure.  ``sleep`` is injectable so tests can run without real
    waits.
    """
    bo = backoff or Backoff()
    disconnect_pending = False
    while True:
        reason: str | None = None
        try:
            async with connect() as events:
                if disconnect_pending:
                    yield IpcReconnected()
                    disconnect_pending = False
                bo.reset()
                async for evt in events:
                    yield evt
                reason = "EOF"
        except Exception as exc:  # surface every failure as a backoff trigger
            reason = str(exc) or exc.__class__.__name__
        yield IpcDisconnected(reason=reason)
        disconnect_pending = True
        await sleep(bo.next())
