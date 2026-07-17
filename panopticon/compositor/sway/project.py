"""Sway adapter — i3ipc-facing seam.

Holds :class:`IpcEvent` (relocated from the retired ``sway_watcher.ipc``
— DD9/V1): one raw i3ipc event, the boundary type the i3ipc client
constructs and the Sway session consumes. The tree-walk projection
helpers that build a :class:`~panopticon.compositor.model.DesktopState`
join this module in PHASE-02.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IpcEvent:
    """One IPC event from the compositor."""

    kind: str
    payload: dict[str, Any]
