"""Niri session glue + neutral diff emission (SL-003 design §5.4).

:class:`NiriSession` is the impure glue between :func:`~panopticon.compositor.niri.protocol.frames`
and the neutral observation stream: a two-mode machine. In *burst mode* it folds
every event into the projection but emits nothing until BOTH ``WindowsChanged``
and ``WorkspacesChanged`` have landed, then yields the ``snapshot`` (DL-2 / INV-N2;
an empty ``DesktopState`` is a valid snapshot, not a withheld one). In *live mode*
it diffs ``to_state`` after each event and emits the highest-precedence changed
field (D10). Overview is inert by construction — the projection ignores
``WindowFocusChanged`` / ``OverviewOpenedOrClosed`` (DL-6), so a gesture moves no
tracked state and :func:`diff_state` returns ``None``. ``diff_state`` and its
precedence live in :mod:`panopticon.compositor.diff`, shared with umbriel.

:class:`NiriClient` names ``producer="niri"`` and hands ``run_watcher`` a session
over ``frames(sock_path)`` — the only impurity, mirroring ``I3ipcSwayClient``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from panopticon.compositor.diff import compact, diff_state
from panopticon.compositor.model import DesktopObservation, DesktopState
from panopticon.compositor.niri.projection import NiriProjection, event_variant
from panopticon.compositor.niri.protocol import frames

__all__ = ["NiriClient", "NiriSession", "diff_state"]

_FULL_STATE = frozenset({"WindowsChanged", "WorkspacesChanged"})


class NiriSession:
    """A live niri session projected as a snapshot-first neutral stream."""

    def __init__(self, frames: Callable[[], AsyncIterator[dict[str, Any]]]) -> None:
        self._frames = frames

    async def observations(self) -> AsyncIterator[DesktopObservation]:
        proj = NiriProjection()
        pending = set(_FULL_STATE)  # full-state categories not yet applied
        state = DesktopState()
        snapshotted = False
        async for event in self._frames():
            proj = proj.apply(event)
            if not snapshotted:
                pending.discard(event_variant(event))
                if pending:  # burst incomplete -> buffer, emit nothing (INV-N2)
                    continue
                state = proj.to_state()
                snapshotted = True
                yield DesktopObservation("snapshot", compact(state.to_dict()), state)
                continue
            new_state = proj.to_state()
            obs = diff_state(state, new_state)
            if obs is not None:
                state = new_state
                yield obs


class NiriClient:
    """A :class:`CompositorClient` over the niri event stream at ``sock_path``."""

    producer = "niri"

    def __init__(self, sock_path: str) -> None:
        self._sock = sock_path

    def session(self):
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[NiriSession]:
        yield NiriSession(lambda: frames(self._sock))
