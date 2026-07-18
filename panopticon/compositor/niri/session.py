"""Niri session glue + neutral diff emission (SL-003 design §5.4).

:class:`NiriSession` is the impure glue between :func:`~panopticon.compositor.niri.protocol.frames`
and the neutral observation stream: a two-mode machine. In *burst mode* it folds
every event into the projection but emits nothing until BOTH ``WindowsChanged``
and ``WorkspacesChanged`` have landed, then yields the ``snapshot`` (DL-2 / INV-N2;
an empty ``DesktopState`` is a valid snapshot, not a withheld one). In *live mode*
it diffs ``to_state`` after each event and emits the highest-precedence changed
field (D10). Overview is inert by construction — the projection ignores
``WindowFocusChanged`` / ``OverviewOpenedOrClosed`` (DL-6), so a gesture moves no
tracked state and :func:`diff_state` returns ``None``.

:class:`NiriClient` names ``producer="niri"`` and hands ``run_watcher`` a session
over ``frames(sock_path)`` — the only impurity, mirroring ``I3ipcSwayClient``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.compositor.niri.projection import NiriProjection, event_variant
from panopticon.compositor.niri.protocol import frames

_FULL_STATE = frozenset({"WindowsChanged", "WorkspacesChanged"})


def diff_state(prior: DesktopState, new: DesktopState) -> DesktopObservation | None:
    """The neutral observation for a state transition, or ``None`` if unchanged.

    Precedence (D10): workspace/output change -> ``workspace_focus``; else a change
    of focused-window identity -> ``window_focus``; else a title-only change ->
    ``window_title``. ``fields`` carry the full new state; the deriver rekeys from
    ``state`` (INV-N3 is about event *names*)."""
    if new == prior:
        return None
    fields = _compact(new.to_dict())
    if (new.workspace, new.output) != (prior.workspace, prior.output):
        return DesktopObservation("workspace_focus", fields, new)
    if _identity(new.window) != _identity(prior.window):
        return DesktopObservation("window_focus", fields, new)
    return DesktopObservation("window_title", fields, new)


def _identity(window: WindowRef | None) -> tuple[int | None, str | None, int | None]:
    """A window's identity sans title — title changes are their own event."""
    return (window.window_id, window.app_id, window.pid) if window else (None, None, None)


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


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
                yield DesktopObservation("snapshot", _compact(state.to_dict()), state)
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
