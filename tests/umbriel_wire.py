"""Shared builders for umbriel IPC wire events (test support, SL-005).

The single source of the raw ``dict`` shapes umbriel emits over its subscribe
socket, used by the projection, session, and equivalence suites so the wire
vocabulary lives in one place (no parallel builders per test file). Field shapes
are taken from the banked golden captures (``tests/fixtures/umbriel/``).

Every event is ``{"event": "<family>", "data": [...]}`` — a full snapshot, not a
delta (design §5.2).
"""

from __future__ import annotations


def win(id: str, **over) -> dict:
    """An umbriel Window record.

    Defaults: ghostty, pid 618860, on workspace ``DP-3:1``, not active/focused.
    ``workspace=""`` marks a scratchpad window; ``pid=-1`` an XWayland surface.
    """
    base = {
        "id": id,
        "app_id": "com.mitchellh.ghostty",
        "pid": 618860,
        "title": f"win-{id}",
        "workspace": "DP-3:1",
        "active": False,
        "focused": False,
    }
    return {**base, **over}


def ws(id: str, index: int, **over) -> dict:
    """An umbriel Workspace record on ``DP-3`` (unnamed, unfocused) by default.

    ``id`` is the composite ``"<output>:<opaque-id>"``; ``index`` is the display
    index (distinct from the id suffix — capture-0 L2). ``name`` defaults to
    ``str(index)`` with ``named=False`` (an unnamed workspace renders its index).
    """
    base = {
        "id": id,
        "index": index,
        "name": str(index),
        "named": False,
        "output": id.split(":", 1)[0],
        "active": False,
        "focused": False,
        "occupied": True,
    }
    return {**base, **over}


def windows(*wins: dict) -> dict:
    return {"event": "windows", "data": list(wins)}


def workspaces(*spaces: dict) -> dict:
    return {"event": "workspaces", "data": list(spaces)}
