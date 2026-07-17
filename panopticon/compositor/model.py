"""Compositor-neutral focus model and adapter contracts.

The neutral core deals in three data shapes and two protocols, all
free of any Sway/Niri specifics:

* :class:`WindowRef` — window identity (id/app/pid/title).
* :class:`DesktopState` — the currently-focused window plus its
  workspace/output. ``to_dict()`` flattens to the exact key set the
  ``current/*.json`` snapshot carries (``con_id`` renamed ``window_id``).
* :class:`DesktopObservation` — one normalized transition an adapter
  yields: an event name, its per-event ``fields`` (preserved verbatim),
  and the re-derived :class:`DesktopState`.

An adapter implements :class:`CompositorSession` (a stream of
observations whose *first* item is always the snapshot — the pull->push
inversion) behind a :class:`CompositorClient` factory that names its
``producer``. The neutral runner and encoder consume only these types.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class WindowRef:
    """Identity of a single window. All fields best-effort/optional."""

    window_id: int | None = None
    app_id: str | None = None
    pid: int | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class DesktopState:
    """The focused window and its location. Subsumes the old FocusState."""

    window: WindowRef | None = None
    workspace: str | None = None
    output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Flatten to the ``current/*.json`` payload (``con_id``->``window_id``).

        An empty state yields the six-key all-``None`` shape today's
        empty ``FocusState`` writes.
        """
        w = self.window or WindowRef()
        return {
            "window_id": w.window_id,
            "app_id": w.app_id,
            "pid": w.pid,
            "title": w.title,
            "workspace": self.workspace,
            "output": self.output,
        }


@dataclass(frozen=True, slots=True)
class DesktopObservation:
    """One normalized transition: event name, per-event fields, and state.

    ``fields`` is the event-specific payload preserved verbatim (the
    encoder spreads it and injects only ``source``/``producer``); only
    ``state`` is re-derived by the adapter's projection.
    """

    event: str
    fields: dict[str, Any]
    state: DesktopState


@runtime_checkable
class CompositorSession(Protocol):
    """A live adapter session: a stream of observations, snapshot first."""

    def observations(self) -> AsyncIterator[DesktopObservation]: ...


@runtime_checkable
class CompositorClient(Protocol):
    """A factory for short-lived sessions, naming its producer."""

    producer: str

    def session(self) -> AbstractAsyncContextManager[CompositorSession]: ...
