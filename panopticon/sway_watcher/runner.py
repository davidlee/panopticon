"""The sway-watcher event loop.

Two layers:

* :func:`process_session` drives one connected session: take a snapshot
  via ``get_tree``, iterate the event stream, write each transformed
  :class:`~panopticon.schema.Event` and the updated current-state file.
  Pure async — no IPC; takes an :class:`AsyncSession` protocol so tests
  can plug in a fake.
* :func:`run_watcher` is the outer reconnect-with-backoff loop. Opens
  a session, hands it to :func:`process_session`, writes the matching
  ``sway_reconnected`` / ``sway_disconnected`` events on transitions,
  and sleeps via the configured :class:`Backoff` between attempts.

The i3ipc-python adapter lives in a separate module so this file
stays unit-testable without a running compositor.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

from panopticon.store import RawStore
from panopticon.sway_watcher.events import (
    snapshot_event,
    sway_disconnected_event,
    sway_reconnected_event,
    transform,
)
from panopticon.sway_watcher.ipc import Backoff, IpcEvent
from panopticon.sway_watcher.state import FocusState, focus_state_from_tree

log = logging.getLogger("panopticon.sway")


class AsyncSession(Protocol):
    """A live IPC session: event stream + tree query."""

    def events(self) -> AsyncIterator[IpcEvent]: ...

    async def get_tree(self) -> dict[str, Any]: ...


@runtime_checkable
class AsyncSwayClient(Protocol):
    """A factory for short-lived IPC sessions."""

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


async def process_session(
    session: AsyncSession,
    store: RawStore,
    state: FocusState,
) -> FocusState:
    """Run one session to completion. Returns the FocusState at EOF.

    Reconciles via ``get_tree`` first so the watcher's state matches
    the compositor's after any prior gap. Writes the snapshot event
    + ``current/sway.json``, then streams transformed events until
    the session's event iterator finishes.
    """
    log.debug("requesting initial get_tree")
    tree = await session.get_tree()
    state = focus_state_from_tree(tree)
    log.info("snapshot: app_id=%s workspace=%s title=%r",
             state.app_id, state.workspace, state.title)
    store.write(snapshot_event(state))
    store.write_current(state.to_dict())
    async for raw in session.events():
        log.debug("ipc: kind=%s change=%s", raw.kind, raw.payload.get("change"))
        event, state = transform(raw.kind, raw.payload, state)
        if event is not None:
            log.info("%s: app_id=%s title=%r",
                     event.event, state.app_id, state.title)
            store.write(event)
            store.write_current(state.to_dict())
    log.debug("session events iterator exhausted")
    return state


async def run_watcher(
    client: AsyncSwayClient,
    store: RawStore,
    *,
    backoff: Backoff | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Drive the sway watcher forever: connect → session → reconnect.

    Cancellation via :exc:`asyncio.CancelledError` is propagated; all
    other exceptions are caught, logged as a ``sway_disconnected``
    event, and trigger a backoff-delayed reconnect.
    """
    bo = backoff or Backoff()
    state = FocusState()
    reconnecting = False
    while True:
        reason: str | None = None
        try:
            log.debug("opening sway session")
            async with client.session() as sess:
                if reconnecting:
                    log.info("reconnected to sway")
                    store.write(sway_reconnected_event())
                    reconnecting = False
                bo.reset()
                state = await process_session(sess, store, state)
                reason = "EOF"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # disconnect → backoff → retry
            reason = str(exc) or exc.__class__.__name__
        log.warning("sway disconnected: %s", reason)
        store.write(sway_disconnected_event(reason))
        reconnecting = True
        await sleep(bo.next())
