"""Sway tree projection — pure helpers that read an i3ipc ``get_tree``.

Two jobs, both pure (no I/O, no IPC, no globals):

* :func:`focus_state_from_tree` derives a
  :class:`~panopticon.compositor.model.DesktopState` from a ``get_tree``
  response via focus + ancestry (the snapshot).
* :func:`build_location_index` walks the tree once, mapping every
  container id to its ``(workspace, output)`` — the location index the
  live session consults on ``window::focus`` (the D5 fix: location comes
  from the focused window's real ancestry, never copied from prior state).

Also holds :class:`IpcEvent` (relocated from the retired
``sway_watcher.ipc`` — DD9/V1): the raw-event boundary type the i3ipc
client constructs and the session consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from panopticon.compositor.model import DesktopState, WindowRef


@dataclass(frozen=True, slots=True)
class IpcEvent:
    """One IPC event from the compositor."""

    kind: str
    payload: dict[str, Any]


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


def focus_state_from_tree(tree: dict[str, Any]) -> DesktopState:
    """Derive a :class:`DesktopState` from a ``get_tree`` response."""
    focused = find_focused(tree)
    if focused is None:
        return DesktopState()
    con_id = focused.get("id")
    window = WindowRef(
        window_id=con_id,
        app_id=app_id_from_container(focused),
        pid=focused.get("pid"),
        title=focused.get("name"),
    )
    return DesktopState(
        window=window,
        workspace=(
            ancestor_name_of_type(tree, con_id, "workspace") if con_id is not None else None
        ),
        output=(
            ancestor_name_of_type(tree, con_id, "output") if con_id is not None else None
        ),
    )


def build_location_index(tree: dict[str, Any]) -> dict[int, tuple[str | None, str | None]]:
    """Map every container id to its ``(workspace, output)`` in one walk.

    The live session seeds this from the snapshot and refreshes it on
    structural events, then looks a focused container up here so
    ``window::focus`` reports the window's real ancestry (D5).
    """
    index: dict[int, tuple[str | None, str | None]] = {}

    def walk(node: dict[str, Any], workspace: str | None, output: str | None) -> None:
        if node.get("type") == "workspace":
            workspace = node.get("name")
        elif node.get("type") == "output":
            output = node.get("name")
        nid = node.get("id")
        if nid is not None:
            index[nid] = (workspace, output)
        for child in _children(node):
            walk(child, workspace, output)

    walk(tree, None, None)
    return index


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
