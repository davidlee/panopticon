"""Focused-window state model and ``get_tree``-derived snapshots.

:class:`FocusState` is the watcher's in-memory mirror of the
compositor: which container, app, workspace, and output are focused
right now. It also serializes to the JSON object written to
``current/sway.json`` so external consumers (waybar, future tools) can
poll one file instead of subscribing.

Tree-walking helpers are pure: no I/O, no IPC, no globals. The
watcher passes them the JSON dict returned by ``get_tree``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FocusState:
    """Snapshot of the currently-focused container."""

    con_id: int | None = None
    app_id: str | None = None
    pid: int | None = None
    title: str | None = None
    workspace: str | None = None
    output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "con_id": self.con_id,
            "app_id": self.app_id,
            "pid": self.pid,
            "title": self.title,
            "workspace": self.workspace,
            "output": self.output,
        }


def app_id_from_container(con: dict[str, Any]) -> str | None:
    """Best-effort app identity for a Sway container.

    Native Wayland clients expose ``app_id``; XWayland clients expose
    ``window_properties.class`` / ``.instance`` instead. Prefer native
    > class > instance, matching the convention in the IPC brief.
    """
    if con.get("app_id"):
        return con["app_id"]
    wp = con.get("window_properties") or {}
    return wp.get("class") or wp.get("instance") or None


def find_focused(node: dict[str, Any]) -> dict[str, Any] | None:
    """Return the deepest container with ``focused: true``, or ``None``.

    Sway marks every container on the active focus chain as focused;
    the leaf is the window the user actually sees. A depth-first walk
    that prefers later matches surfaces the leaf.
    """
    result = node if node.get("focused") else None
    for child in _children(node):
        deeper = find_focused(child)
        if deeper is not None:
            result = deeper
    return result


def ancestor_name_of_type(
    tree: dict[str, Any],
    target_id: int,
    ancestor_type: str,
) -> str | None:
    """Walk ``tree`` looking for ``target_id``; return the ``name`` of its
    nearest ancestor of ``ancestor_type`` (e.g. ``"workspace"`` or
    ``"output"``), or ``None`` if not found.
    """
    return _walk_ancestor(tree, target_id, ancestor_type, current=None)


def focus_state_from_tree(tree: dict[str, Any]) -> FocusState:
    """Derive a :class:`FocusState` from a ``get_tree`` response."""
    focused = find_focused(tree)
    if focused is None:
        return FocusState()
    con_id = focused.get("id")
    return FocusState(
        con_id=con_id,
        app_id=app_id_from_container(focused),
        pid=focused.get("pid"),
        title=focused.get("name"),
        workspace=(
            ancestor_name_of_type(tree, con_id, "workspace") if con_id is not None else None
        ),
        output=(
            ancestor_name_of_type(tree, con_id, "output") if con_id is not None else None
        ),
    )


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return (node.get("nodes") or []) + (node.get("floating_nodes") or [])


def _walk_ancestor(
    node: dict[str, Any],
    target_id: int,
    ancestor_type: str,
    current: str | None,
) -> str | None:
    if node.get("type") == ancestor_type:
        current = node.get("name")
    if node.get("id") == target_id:
        return current
    for child in _children(node):
        found = _walk_ancestor(child, target_id, ancestor_type, current)
        if found is not None:
            return found
    return None
