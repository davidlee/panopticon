"""Normalize raw Sway IPC events to the panopticon schema-v1 wire format.

:func:`transform` is the single entry point: given the IPC ``kind``
(``"window"``, ``"workspace"``, …), the event ``payload`` dict, and the
current :class:`~panopticon.sway_watcher.state.FocusState`, it returns
``(event_or_none, new_state)``. Callers write the event to the
:class:`~panopticon.store.RawStore` and persist the new state in
``current/sway.json``.

The functions in this module are pure — no IPC, no I/O — so each
transition is unit-testable against a fixture payload.

Synthetic events the watcher emits itself (``snapshot``,
``sway_disconnected``, ``sway_reconnected``) live as small factory
helpers at the bottom.
"""

from __future__ import annotations

from typing import Any

from panopticon.schema import Event, make_event
from panopticon.sway_watcher.state import FocusState, app_id_from_container

__all__ = [
    "snapshot_event",
    "sway_disconnected_event",
    "sway_reconnected_event",
    "transform",
]


def transform(
    kind: str,
    payload: dict[str, Any],
    state: FocusState,
) -> tuple[Event | None, FocusState]:
    """Map one IPC event to an optional :class:`Event` and an updated state."""
    if kind == "window":
        return _window(payload, state)
    if kind == "workspace":
        return _workspace(payload, state)
    return None, state


# ---- window changes ----

_PASSTHROUGH_WINDOW_CHANGES = {
    "move": "window_move",
    "fullscreen_mode": "window_fullscreen_mode",
    "urgent": "window_urgent",
}


def _window(
    payload: dict[str, Any], state: FocusState
) -> tuple[Event | None, FocusState]:
    change = payload.get("change")
    container = payload.get("container") or {}
    if change == "focus":
        return _on_window_focus(container, state)
    if change == "title":
        return _on_window_title(container, state)
    if change == "new":
        return _on_window_new(container, state)
    if change == "close":
        return _on_window_close(container, state)
    if change in _PASSTHROUGH_WINDOW_CHANGES:
        return _passthrough_window(_PASSTHROUGH_WINDOW_CHANGES[change], container), state
    return None, state


def _on_window_focus(
    container: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    new_state = FocusState(
        con_id=container.get("id"),
        app_id=app_id_from_container(container),
        pid=container.get("pid"),
        title=container.get("name"),
        workspace=state.workspace,
        output=state.output,
    )
    ev = make_event("sway", "window_focus", **_compact(new_state.to_dict()))
    return ev, new_state


def _on_window_title(
    container: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    new_title = container.get("name")
    new_state = FocusState(
        con_id=state.con_id,
        app_id=state.app_id,
        pid=state.pid,
        title=new_title,
        workspace=state.workspace,
        output=state.output,
    )
    fields = _compact(
        {
            "con_id": state.con_id,
            "app_id": state.app_id,
            "pid": state.pid,
            "old_title": state.title,
            "title": new_title,
            "workspace": state.workspace,
        }
    )
    return make_event("sway", "window_title", **fields), new_state


def _on_window_new(
    container: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    return _passthrough_window("window_new", container), state


def _on_window_close(
    container: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    ev = _passthrough_window("window_close", container)
    new_state = FocusState() if container.get("id") == state.con_id else state
    return ev, new_state


def _passthrough_window(event_name: str, container: dict[str, Any]) -> Event:
    fields = _compact(
        {
            "con_id": container.get("id"),
            "app_id": app_id_from_container(container),
            "pid": container.get("pid"),
            "title": container.get("name"),
        }
    )
    return make_event("sway", event_name, **fields)


# ---- workspace changes ----


def _workspace(
    payload: dict[str, Any], state: FocusState
) -> tuple[Event | None, FocusState]:
    change = payload.get("change")
    if change == "focus":
        return _on_workspace_focus(payload, state)
    if change == "urgent":
        return _on_workspace_urgent(payload, state)
    return None, state


def _on_workspace_focus(
    payload: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    current = payload.get("current") or {}
    old = payload.get("old") or {}
    new_state = FocusState(
        con_id=state.con_id,
        app_id=state.app_id,
        pid=state.pid,
        title=state.title,
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
    return make_event("sway", "workspace_focus", **fields), new_state


def _on_workspace_urgent(
    payload: dict[str, Any], state: FocusState
) -> tuple[Event, FocusState]:
    current = payload.get("current") or {}
    fields = _compact(
        {
            "workspace": current.get("name"),
            "urgent": current.get("urgent", True),
        }
    )
    return make_event("sway", "workspace_urgent", **fields), state


# ---- synthetic events (emitted by the watcher itself) ----


def snapshot_event(state: FocusState) -> Event:
    """Build the snapshot event emitted at init/reconnect."""
    return make_event("sway", "snapshot", **_compact(state.to_dict()))


def sway_disconnected_event(reason: str | None = None) -> Event:
    fields = {"reason": reason} if reason else {}
    return make_event("sway", "sway_disconnected", **fields)


def sway_reconnected_event() -> Event:
    return make_event("sway", "sway_reconnected")


# ---- helpers ----


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` so emitted lines stay tidy."""
    return {k: v for k, v in d.items() if v is not None}
