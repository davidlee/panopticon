"""Neutral state-transition diffing, shared across streaming adapters.

Both the niri and umbriel sessions are *snapshot-first pure-streaming*
adapters: they fold each compositor event into a projection, recompute the
neutral :class:`DesktopState`, and emit the highest-precedence changed field.
:func:`diff_state` is that pure core — one implementation, no per-adapter copy
(SL-003 §5.4, SL-005 / ISS-001).

Precedence (ISS-001): a change of **focused-window identity** (including focus
leaving to no window) wins — ``window_focus`` — so the deriver rekeys app +
workspace fully and a focus-to-nothing transition closes the running segment.
Only when the same window stays focused does a workspace/output change surface as
``workspace_focus`` (a location relabel the deriver applies while keeping the
app). A title-only change is ``window_title``. Identity beats location because
the deriver's ``workspace_focus`` branch *retains* the running app — correct only
when the window really is unchanged; masking a genuine window switch behind a
simultaneous workspace change mis-attributes the new focus to the old app.
"""

from __future__ import annotations

from typing import Any

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef


def diff_state(prior: DesktopState, new: DesktopState) -> DesktopObservation | None:
    """The neutral observation for a state transition, or ``None`` if unchanged."""
    if new == prior:
        return None
    fields = compact(new.to_dict())
    if _identity(new.window) != _identity(prior.window):
        return DesktopObservation("window_focus", fields, new)
    if (new.workspace, new.output) != (prior.workspace, prior.output):
        return DesktopObservation("workspace_focus", fields, new)
    return DesktopObservation("window_title", fields, new)


def _identity(
    window: WindowRef | None,
) -> tuple[int | str | None, str | None, int | None]:
    """A window's identity sans title — title changes are their own event."""
    return (window.window_id, window.app_id, window.pid) if window else (None, None, None)


def compact(d: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values — the per-event ``fields`` carry only what is set."""
    return {k: v for k, v in d.items() if v is not None}
