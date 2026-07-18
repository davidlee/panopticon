"""Shared builders for niri IPC wire events (test support, SL-003).

The single source of the raw ``dict`` shapes niri emits over ``$NIRI_SOCKET``,
used by the projection, session, and equivalence suites so the wire vocabulary
lives in one place (no parallel builders per test file).
"""

from __future__ import annotations


def win(id: int, **over) -> dict:
    """A niri Window record (defaults: firefox, pid 12345, title win-<id>)."""
    return {"id": id, "app_id": "firefox", "pid": 12345, "title": f"win-{id}", **over}


def ws(id: int, idx: int, **over) -> dict:
    """A niri Workspace record on ``DP-3`` (unnamed, unfocused, empty) by default."""
    base = {
        "id": id,
        "idx": idx,
        "name": None,
        "output": "DP-3",
        "is_focused": False,
        "active_window_id": None,
    }
    return {**base, **over}


def windows_changed(*windows: dict) -> dict:
    return {"WindowsChanged": {"windows": list(windows)}}


def workspaces_changed(*workspaces: dict) -> dict:
    return {"WorkspacesChanged": {"workspaces": list(workspaces)}}
