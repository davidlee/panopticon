"""Pure Umbriel projection (SL-005 design §5.2).

``UmbrielProjection.apply`` folds native umbriel IPC events into an immutable
adapter-private state; ``to_state`` derives the neutral :class:`DesktopState`.
Umbriel emits a **full snapshot per event**, so ``apply`` is a snapshot-*replace*,
not a delta accumulator (contrast :mod:`panopticon.compositor.niri.projection`):
there is no novelty detection and no window-close handling.

Focus is two-tier and pure (DL-4): **Tier-1** the unique ``active`` window (the
seat's keyboard focus, 0-or-1 globally); **Tier-2** the focused window on the
focused workspace, used only when ``active`` transiently empties. ``_locate``
resolves the workspace label from the *retained* workspaces snapshot — never from
the composite id suffix (an opaque internal id, not the display index) — and
takes ``output`` from the reliable id prefix when the entry has not yet landed.

``apply`` is total and pure (INV-U1): an unknown event family or field returns an
equal/updated projection, never raises. ``UmbrielWindow``/``UmbrielWorkspace`` are
adapter-private; only ``DesktopState`` crosses the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from panopticon.compositor.model import DesktopState, WindowRef


@dataclass(frozen=True, slots=True)
class UmbrielWindow:
    """Adapter-private window; only the neutral subset is surfaced."""

    id: str
    app_id: str | None
    pid: int | None  # raw wire pid; normalised by _pid at the neutral boundary
    title: str | None
    workspace: str | None  # composite ws id ("DP-3:1"), "" ⇒ scratchpad
    active: bool  # seat keyboard focus (0/1 globally)
    focused: bool  # per-workspace focus flag (multiple true at once)


@dataclass(frozen=True, slots=True)
class UmbrielWorkspace:
    """Adapter-private workspace. ``id`` is the composite ``"<output>:<opaque>"``."""

    id: str
    name: str | None
    named: bool
    index: int | None
    output: str | None
    focused: bool


@dataclass(frozen=True, slots=True)
class UmbrielProjection:
    """Immutable fold of the umbriel subscribe stream. ``apply`` is total + pure."""

    windows: tuple[UmbrielWindow, ...] = ()
    workspaces: tuple[UmbrielWorkspace, ...] = ()
    seen_windows: bool = False
    seen_workspaces: bool = False

    def apply(self, event: Any) -> UmbrielProjection:
        """Fold one native event in; unknown families/fields are inert (INV-U1)."""
        if not isinstance(event, dict):
            return self
        family = event.get("event")
        data = event.get("data")
        if not isinstance(data, list):
            return self  # missing/malformed payload → inert
        if family == "windows":
            wins = tuple(w for w in map(_window, data) if w is not None)
            return replace(self, windows=wins, seen_windows=True)
        if family == "workspaces":
            spaces = tuple(w for w in map(_workspace, data) if w is not None)
            return replace(self, workspaces=spaces, seen_workspaces=True)
        return self  # unsubscribed/unknown family (theme, overview, …) → inert

    @property
    def burst_complete(self) -> bool:
        """Both full-snapshot families seen once — the burst terminator (D2)."""
        return self.seen_windows and self.seen_workspaces

    @property
    def focus_coherent(self) -> bool:
        """Is the current focus fully resolvable? (RV-005.2 coherence hold.)

        ``False`` iff a window is focused on a non-empty workspace id absent from
        the retained workspaces map (the new-workspace windows-before-workspaces
        case). ``True`` for no-focus, scratchpad (``""``), and resolved workspaces.
        """
        win = self._focused_window()
        if win is None or not win.workspace:  # no-focus or scratchpad
            return True
        return any(ws.id == win.workspace for ws in self.workspaces)

    def to_state(self) -> DesktopState:
        """Neutral snapshot: two-tier focus (DL-4) + transitive location join."""
        win = self._focused_window()
        if win is None:
            return DesktopState()  # genuine no-focus
        ws = self._workspace_by_id(win.workspace) if win.workspace else None
        label, output = _locate(win.workspace, ws)
        return DesktopState(
            window=WindowRef(win.id, win.app_id, _pid(win.pid), win.title),
            workspace=label,
            output=output,
        )

    # ---- focus derivation (pure) --------------------------------------------

    def _focused_window(self) -> UmbrielWindow | None:
        """Tier-1 the unique active window; Tier-2 the focused-ws focused window."""
        active = [w for w in self.windows if w.active]
        if len(active) == 1:  # Tier-1 — seat focus, unambiguous
            return active[0]
        # Tier-2 — active empty (or >1, ASM-U1): the focused window on the
        # unique focused workspace. No prior state; pure over the two snapshots.
        focused_ws = [ws for ws in self.workspaces if ws.focused]
        if len(focused_ws) != 1:
            return None
        on_ws = [w for w in self.windows if w.focused and w.workspace == focused_ws[0].id]
        return on_ws[0] if len(on_ws) == 1 else None

    def _workspace_by_id(self, ws_id: str) -> UmbrielWorkspace | None:
        return next((ws for ws in self.workspaces if ws.id == ws_id), None)


# ---- event record parsing (total) -------------------------------------------


def _window(d: Any) -> UmbrielWindow | None:
    if not isinstance(d, dict) or d.get("id") is None:
        return None
    return UmbrielWindow(
        id=d["id"],
        app_id=d.get("app_id"),
        pid=d.get("pid"),
        title=d.get("title"),
        workspace=d.get("workspace"),
        active=bool(d.get("active")),
        focused=bool(d.get("focused")),
    )


def _workspace(d: Any) -> UmbrielWorkspace | None:
    if not isinstance(d, dict) or d.get("id") is None:
        return None
    return UmbrielWorkspace(
        id=d["id"],
        name=d.get("name"),
        named=bool(d.get("named")),
        index=d.get("index"),
        output=d.get("output"),
        focused=bool(d.get("focused")),
    )


# ---- neutral-boundary helpers -----------------------------------------------


def _locate(ws_id: str | None, ws: UmbrielWorkspace | None) -> tuple[str | None, str | None]:
    """Resolve (workspace label, output) for a focused window's workspace id.

    Label comes ONLY from a resolved workspaces entry (DL-1: ``name`` if named,
    else the display ``index`` — never the id suffix). Unresolved non-empty id →
    label ``None``, output from the reliable id prefix (the coherence-hold case).
    Scratchpad (``""``) / no workspace → ``(None, None)``.
    """
    if ws is not None:
        label = ws.name if ws.named else (str(ws.index) if ws.index is not None else None)
        return label, ws.output
    if not ws_id:  # "" scratchpad or None
        return None, None
    return None, (ws_id.split(":", 1)[0] or None)


def _pid(p: Any) -> int | None:
    """Normalise a wire pid: non-positive → None (XWayland ``-1`` sentinel, DL-9).

    ``type(p) is int`` excludes ``bool`` (a subclass of int) so a stray ``True``
    never reads as pid 1.
    """
    return p if type(p) is int and p > 0 else None
