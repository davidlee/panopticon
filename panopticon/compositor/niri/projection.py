"""Pure Niri projection accumulator (SL-003 design §5.2).

``NiriProjection.apply`` folds native niri IPC events into an immutable
adapter-private state; ``to_state`` derives the neutral :class:`DesktopState`.
Focus flows *workspace -> active window* (DL-6): the projection tracks the
globally-focused workspace and each workspace's ``active_window_id``, and reads
the focused window transitively — the raw ``WindowFocusChanged`` stream is
ignored, which makes overview flapping impossible by construction.

``apply`` is **total and pure** (INV-N1): an unknown variant or a missing field
returns an equal/updated projection, never raises — niri's additive-only wire
guarantee met with ignore-and-continue. ``NiriWindow``/``NiriWorkspace`` are
adapter-private; only ``DesktopState`` crosses the boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from panopticon.compositor.model import DesktopState, WindowRef


def event_variant(event: Any) -> str | None:
    """The niri event's variant tag (its sole top-level key), or ``None`` if the
    event is not a non-empty dict. The one place the wire's tagged-union shape is
    read — shared by :meth:`NiriProjection.apply` and the session's burst gate."""
    if not isinstance(event, dict) or not event:
        return None
    return next(iter(event))


@dataclass(frozen=True, slots=True)
class NiriWindow:
    """Adapter-private window; only the neutral subset is surfaced."""

    id: int
    app_id: str | None = None
    pid: int | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class NiriWorkspace:
    """Adapter-private workspace. ``active_window_id`` is niri's per-workspace
    focus, seeded in the burst and moved by ``WorkspaceActiveWindowChanged``."""

    id: int
    name: str | None
    idx: int | None
    output: str | None
    active_window_id: int | None = None


@dataclass(frozen=True, slots=True)
class NiriProjection:
    """Immutable fold of the niri event stream. ``apply`` is total and pure."""

    windows_by_id: Mapping[int, NiriWindow] = field(default_factory=dict)
    workspaces_by_id: Mapping[int, NiriWorkspace] = field(default_factory=dict)
    focused_workspace_id: int | None = None

    def apply(self, event: Any) -> NiriProjection:
        """Fold one native event in; unknown variants/fields are inert (INV-N1)."""
        variant = event_variant(event)
        if variant is None:
            return self
        handler = _HANDLERS.get(variant)
        if handler is None:  # ignored variant (WindowFocusChanged, overview, ...)
            return self
        body = event[variant]
        if not isinstance(body, dict):
            return self
        return handler(self, body)

    def to_state(self) -> DesktopState:
        """Neutral snapshot: focused workspace -> its active window (DL-6)."""
        ws = self.workspaces_by_id.get(self.focused_workspace_id)
        if ws is None:
            return DesktopState()
        win = (
            self.windows_by_id.get(ws.active_window_id) if ws.active_window_id is not None else None
        )
        window = WindowRef(win.id, win.app_id, win.pid, win.title) if win is not None else None
        workspace = ws.name or (str(ws.idx) if ws.idx is not None else str(ws.id))
        return DesktopState(window=window, workspace=workspace, output=ws.output)


# ---- event -> mutation (design §5.2) ----------------------------------------


def _window(d: dict[str, Any]) -> NiriWindow | None:
    wid = d.get("id")
    if wid is None:
        return None
    return NiriWindow(wid, d.get("app_id"), d.get("pid"), d.get("title"))


def _workspace(d: dict[str, Any]) -> NiriWorkspace | None:
    wid = d.get("id")
    if wid is None:
        return None
    return NiriWorkspace(
        wid, d.get("name"), d.get("idx"), d.get("output"), d.get("active_window_id")
    )


def _windows_changed(proj: NiriProjection, body: dict) -> NiriProjection:
    windows = {w.id: w for w in map(_window, body.get("windows", [])) if w is not None}
    return replace(proj, windows_by_id=windows)


def _workspaces_changed(proj: NiriProjection, body: dict) -> NiriProjection:
    spaces = {w.id: w for w in map(_workspace, body.get("workspaces", [])) if w is not None}
    focused = next(
        (
            raw["id"]
            for raw in body.get("workspaces", [])
            if raw.get("is_focused") and raw.get("id") is not None
        ),
        None,
    )
    return replace(proj, workspaces_by_id=spaces, focused_workspace_id=focused)


def _window_opened_or_changed(proj: NiriProjection, body: dict) -> NiriProjection:
    win = _window(body.get("window", {}))
    if win is None:
        return proj
    return replace(proj, windows_by_id={**proj.windows_by_id, win.id: win})


def _window_closed(proj: NiriProjection, body: dict) -> NiriProjection:
    wid = body.get("id")
    if wid not in proj.windows_by_id:
        return proj
    return replace(proj, windows_by_id={k: v for k, v in proj.windows_by_id.items() if k != wid})


def _workspace_activated(proj: NiriProjection, body: dict) -> NiriProjection:
    if not body.get("focused"):
        return proj
    wid = body.get("id")
    if wid is None:
        return proj
    return replace(proj, focused_workspace_id=wid)


def _workspace_active_window_changed(proj: NiriProjection, body: dict) -> NiriProjection:
    wid = body.get("workspace_id")
    ws = proj.workspaces_by_id.get(wid)
    if ws is None:
        return proj
    updated = replace(ws, active_window_id=body.get("active_window_id"))
    return replace(proj, workspaces_by_id={**proj.workspaces_by_id, wid: updated})


_HANDLERS = {
    "WindowsChanged": _windows_changed,
    "WorkspacesChanged": _workspaces_changed,
    "WindowOpenedOrChanged": _window_opened_or_changed,
    "WindowClosed": _window_closed,
    "WorkspaceActivated": _workspace_activated,
    "WorkspaceActiveWindowChanged": _workspace_active_window_changed,
}
