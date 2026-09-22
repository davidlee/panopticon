"""Umbriel session glue + neutral diff emission (SL-005 design §5.4).

:class:`UmbrielSession` is the impure glue between
:func:`~panopticon.compositor.umbriel.protocol.frames` and the neutral
observation stream — the umbriel analogue of :class:`NiriSession`, a two-mode
machine over the pure :class:`UmbrielProjection` and the SHARED
:func:`~panopticon.compositor.diff.diff_state` (no per-adapter diff copy).

*Burst mode* folds every event but emits nothing until ``burst_complete`` (both
full-snapshot families seen once), then yields the ``snapshot`` (INV-U2; an empty
:class:`DesktopState` is a valid snapshot). It is bounded by ``burst_timeout``: a
socket that sends one family then goes silent-but-open raises → ``run_watcher``
disconnects and backs off, rather than a wedged session (RV-005.5a).

*Live mode* recomputes ``to_state`` after each event and emits the
highest-precedence changed field. A **coherence hold** (RV-005.2) covers the one
umbriel-specific hazard niri lacks: a *new* workspace whose ``windows`` event
leads its ``workspaces`` event leaves the focus resolvable only for output, not
label. The session **withholds** — neither emitting nor advancing its ``prior``
baseline — and folds the next event until ``focus_coherent`` again, then emits a
SINGLE precedence-correct observation with the resolved label (never a None→label
or suffix→label flap). Bounded by ``coherence_timeout``: if coherence never
lands, the session **raises → disconnect/reburst** rather than emit an incoherent
``workspace=None`` live observation that would mis-derive.

:class:`UmbrielClient` names ``producer="umbriel"`` and hands ``run_watcher`` a
session over ``frames(sock_path)`` — the only impurity, mirroring ``NiriClient``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from panopticon.compositor.diff import compact, diff_state
from panopticon.compositor.model import DesktopObservation
from panopticon.compositor.umbriel.projection import UmbrielProjection
from panopticon.compositor.umbriel.protocol import frames

__all__ = ["UmbrielClient", "UmbrielSession", "diff_state"]

_DEFAULT_TIMEOUT = 2.0


class UmbrielSession:
    """A live umbriel session projected as a snapshot-first neutral stream."""

    def __init__(
        self,
        frames: Callable[[], AsyncIterator[dict[str, Any]]],
        *,
        burst_timeout: float = _DEFAULT_TIMEOUT,
        coherence_timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._frames = frames
        self._burst_timeout = burst_timeout
        self._coherence_timeout = coherence_timeout

    async def observations(self) -> AsyncIterator[DesktopObservation]:
        proj = UmbrielProjection()
        events = self._frames()
        try:
            # ---- burst mode: buffer until both families land, then snapshot ----
            async with asyncio.timeout(self._burst_timeout):
                async for event in events:
                    proj = proj.apply(event)
                    if proj.burst_complete:
                        break
                else:  # EOF before burst_complete → partial burst discarded (D2)
                    return
            state = proj.to_state()
            yield DesktopObservation("snapshot", compact(state.to_dict()), state)

            # ---- live mode: diff-emit; coherence-hold a new-workspace race ----
            hold_until: float | None = None
            while True:
                try:
                    if hold_until is None:
                        event = await events.__anext__()
                    else:  # mid-hold: bound the wait by the fixed hold deadline
                        async with asyncio.timeout_at(hold_until):
                            event = await events.__anext__()
                except StopAsyncIteration:
                    return  # EOF → clean disconnect
                proj = proj.apply(event)
                if not proj.focus_coherent:
                    if hold_until is None:  # start the hold; deadline fixed once
                        loop = asyncio.get_running_loop()
                        hold_until = loop.time() + self._coherence_timeout
                    continue  # withhold: no emit, baseline unchanged, fold next
                hold_until = None
                new = proj.to_state()
                obs = diff_state(state, new)
                if obs is not None:
                    state = new
                    yield obs
        finally:
            await events.aclose()


class UmbrielClient:
    """A :class:`CompositorClient` over the umbriel subscribe stream at ``sock_path``."""

    producer = "umbriel"

    def __init__(self, sock_path: str) -> None:
        self._sock = sock_path

    def session(self):
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[UmbrielSession]:
        yield UmbrielSession(lambda: frames(self._sock))
