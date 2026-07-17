"""Sway ``CompositorSession`` — the live projection adapter.

:class:`SwaySession` turns an i3ipc event stream into the neutral
observation stream the runner consumes. Its *first* observation is the
snapshot (pull->push inversion). It holds a live projection — a
``container_id -> (workspace, output)`` location index — seeded by
``get_tree`` and refreshed on structural events; ``window::focus`` reads
window identity from the event payload and location from the index (the
D5 fix: location is the focused window's real ancestry, never copied
from prior state).

The per-event mapping (:func:`map_event` and its helpers) is pure —
given the change payload, prior state, and index it returns a
:class:`DesktopObservation` or ``None``. ``get_tree`` and index
maintenance are the only impurity, confined to the session's loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.compositor.sway.project import (
    IpcEvent,
    app_id_from_container,
    build_location_index,
    focus_state_from_tree,
)

# Changes that restructure the tree — refresh the location index from get_tree
# so a subsequent window::focus reads accurate ancestry (F9). window::focus is
# deliberately absent: focus reads the index, never triggers a get_tree (D5/F2).
_STRUCTURAL: frozenset[tuple[str, str]] = frozenset(
    {
        ("window", "new"),
        ("window", "close"),
        ("window", "move"),
        ("workspace", "focus"),
        ("workspace", "init"),
        ("workspace", "empty"),
    }
)

_PASSTHROUGH_WINDOW_CHANGES = {
    "new": "window_new",
    "move": "window_move",
    "fullscreen_mode": "window_fullscreen_mode",
    "urgent": "window_urgent",
}

LocationIndex = dict[int, tuple[str | None, str | None]]


class SwaySession:
    """One live i3ipc session projected as a neutral observation stream."""

    def __init__(
        self,
        events: Callable[[], AsyncIterator[IpcEvent]],
        get_tree: Callable[[], Awaitable[dict[str, Any]]],
    ) -> None:
        self._events = events
        self._get_tree = get_tree
        self._index: LocationIndex = {}
        self._state = DesktopState()

    async def observations(self) -> AsyncIterator[DesktopObservation]:
        tree = await self._get_tree()
        self._index = build_location_index(tree)
        self._state = focus_state_from_tree(tree)
        yield DesktopObservation("snapshot", _compact(self._state.to_dict()), self._state)
        async for raw in self._events():
            if (raw.kind, raw.payload.get("change")) in _STRUCTURAL:
                self._index = build_location_index(await self._get_tree())
            obs = map_event(raw.kind, raw.payload, self._state, self._index)
            if obs is not None:
                self._state = obs.state
                yield obs


def map_event(
    kind: str,
    payload: dict[str, Any],
    state: DesktopState,
    index: LocationIndex,
) -> DesktopObservation | None:
    """Map one i3ipc event to a neutral observation (or ``None`` to drop it)."""
    if kind == "window":
        return _window(payload, state, index)
    if kind == "workspace":
        return _workspace(payload, state)
    return None


# ---- window changes ----


def _window(
    payload: dict[str, Any], state: DesktopState, index: LocationIndex
) -> DesktopObservation | None:
    change = payload.get("change")
    container = payload.get("container") or {}
    if change == "focus":
        return _window_focus(container, index)
    if change == "title":
        return _window_title(container, state)
    if change == "close":
        return _window_close(container, state)
    if change in _PASSTHROUGH_WINDOW_CHANGES:
        return _passthrough(_PASSTHROUGH_WINDOW_CHANGES[change], container, state)
    return None


def _window_focus(container: dict[str, Any], index: LocationIndex) -> DesktopObservation:
    con_id = container.get("id")
    window = WindowRef(
        window_id=con_id,
        app_id=app_id_from_container(container),
        pid=container.get("pid"),
        title=container.get("name"),
    )
    workspace, output = index.get(con_id, (None, None))
    st = DesktopState(window=window, workspace=workspace, output=output)
    return DesktopObservation("window_focus", _compact(st.to_dict()), st)


def _window_title(container: dict[str, Any], state: DesktopState) -> DesktopObservation:
    new_title = container.get("name")
    prior = state.window or WindowRef()
    window = WindowRef(prior.window_id, prior.app_id, prior.pid, new_title)
    st = DesktopState(window=window, workspace=state.workspace, output=state.output)
    fields = _compact(
        {
            "window_id": prior.window_id,
            "app_id": prior.app_id,
            "pid": prior.pid,
            "old_title": prior.title,
            "title": new_title,
            "workspace": state.workspace,
        }
    )
    return DesktopObservation("window_title", fields, st)


def _window_close(container: dict[str, Any], state: DesktopState) -> DesktopObservation:
    focused_id = state.window.window_id if state.window else None
    new_state = DesktopState() if container.get("id") == focused_id else state
    return DesktopObservation("window_close", _window_fields(container), new_state)


def _passthrough(
    event_name: str, container: dict[str, Any], state: DesktopState
) -> DesktopObservation:
    return DesktopObservation(event_name, _window_fields(container), state)


def _window_fields(container: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "window_id": container.get("id"),
            "app_id": app_id_from_container(container),
            "pid": container.get("pid"),
            "title": container.get("name"),
        }
    )


# ---- workspace changes ----


def _workspace(payload: dict[str, Any], state: DesktopState) -> DesktopObservation | None:
    change = payload.get("change")
    if change == "focus":
        return _workspace_focus(payload, state)
    if change == "urgent":
        return _workspace_urgent(payload, state)
    return None


def _workspace_focus(payload: dict[str, Any], state: DesktopState) -> DesktopObservation:
    current = payload.get("current") or {}
    old = payload.get("old") or {}
    st = DesktopState(
        window=state.window,
        workspace=current.get("name"),
        output=current.get("output"),
    )
    fields = _compact(
        {
            "old_workspace": old.get("name"),
            "workspace": current.get("name"),
            "output": current.get("output"),
        }
    )
    return DesktopObservation("workspace_focus", fields, st)


def _workspace_urgent(payload: dict[str, Any], state: DesktopState) -> DesktopObservation:
    current = payload.get("current") or {}
    fields = _compact(
        {"workspace": current.get("name"), "urgent": current.get("urgent", True)}
    )
    return DesktopObservation("workspace_urgent", fields, state)


# ---- helpers ----


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` so emitted lines stay tidy."""
    return {k: v for k, v in d.items() if v is not None}
