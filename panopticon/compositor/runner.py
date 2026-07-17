"""The compositor-neutral event loop.

Two layers, learning *nothing* compositor-specific (neutrality is
subtraction — the old ``get_tree`` pull is gone):

* :func:`process_session` drives one connected session: iterate the
  adapter's ``observations()`` — whose first item is the snapshot
  (pull->push inversion, DD2) — encoding each to an :class:`Event` and
  writing it plus the current-state file. No state threading, no return
  (F3).
* :func:`run_watcher` is the outer reconnect-with-backoff loop. It owns
  the lifecycle events, now neutral: ``compositor_reconnected`` on a
  non-first connect and ``compositor_disconnected`` on drop, both routed
  through :func:`~panopticon.compositor.events.encode` (INV-2). The fresh
  session supplies the post-reconnect snapshot.

:class:`Backoff` (relocated from the retired ``sway_watcher.ipc``) lives
here — the only reconnect primitive the neutral core needs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from panopticon.compositor.events import encode
from panopticon.compositor.model import (
    CompositorClient,
    CompositorSession,
    DesktopObservation,
    DesktopState,
)
from panopticon.store import RawStore

log = logging.getLogger("panopticon.compositor")


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


async def process_session(
    session: CompositorSession,
    store: RawStore,
    producer: str,
) -> None:
    """Run one session to completion.

    The adapter yields its own snapshot first, then deltas, then EOF.
    Each observation is encoded and written along with the current-state
    file (INV-1). The runner no longer knows how state is acquired.
    """
    async for obs in session.observations():
        log.debug("obs: event=%s", obs.event)
        store.write(encode(obs, producer))
        store.write_current(obs.state.to_dict())


def _lifecycle(event: str, reason: str | None = None) -> DesktopObservation:
    """Build a lifecycle observation (empty state) for encode()."""
    fields = {"reason": reason} if reason else {}
    return DesktopObservation(event=event, fields=fields, state=DesktopState())


async def run_watcher(
    client: CompositorClient,
    store: RawStore,
    *,
    backoff: Backoff | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Drive the watcher forever: connect -> session -> reconnect.

    Cancellation via :exc:`asyncio.CancelledError` is propagated; all
    other exceptions become a ``compositor_disconnected`` event and a
    backoff-delayed reconnect.
    """
    bo = backoff or Backoff()
    producer = client.producer
    reconnecting = False
    while True:
        reason: str | None = None
        try:
            log.debug("opening %s session", producer)
            async with client.session() as sess:
                if reconnecting:
                    log.info("reconnected to %s", producer)
                    store.write(encode(_lifecycle("compositor_reconnected"), producer))
                    reconnecting = False
                bo.reset()
                await process_session(sess, store, producer)
                reason = "EOF"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # disconnect -> backoff -> retry
            reason = str(exc) or exc.__class__.__name__
        log.warning("%s disconnected: %s", producer, reason)
        store.write(encode(_lifecycle("compositor_disconnected", reason), producer))
        reconnecting = True
        await sleep(bo.next())
