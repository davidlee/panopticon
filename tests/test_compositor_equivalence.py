"""Cross-compositor equivalence (SL-003 PHASE-02, VT-4, F-6).

The same user action — *switch to workspace "2" on output DP-2, landing focus on
window B* — driven through the Sway and Niri sessions must yield the same neutral
event-name sequence, connector-name outputs on both, and the same
workspace-transition shape. This is the contract the deriver depends on (INV-N3):
two producers, one neutral vocabulary.

Granularity note (design D-P02-1): a *single* cross-output focus collapses to one
``workspace_focus`` in niri but one ``window_focus`` in sway (sway reads location
from the ancestry index). The scenario here is the two-step transition both
adapters decompose identically — ``[snapshot, workspace_focus, window_focus]``.
It does not assert the intermediate ``workspace_focus`` window (niri carries None,
sway keeps the prior window — a real, documented adapter difference).
"""

from __future__ import annotations

from panopticon.compositor.model import DesktopObservation
from panopticon.compositor.niri.session import NiriSession
from panopticon.compositor.sway.project import IpcEvent
from panopticon.compositor.sway.session import SwaySession
from tests.niri_wire import win, windows_changed, workspaces_changed, ws
from tests.test_compositor_niri_session import _frames_from
from tests.test_compositor_sway_session import _events_from, _get_tree_returning, _tree

# window A: ghostty on workspace "1" / output DP-3 (initial focus)
# window B: firefox on workspace "2" / output DP-2 (the switch target)
_A = {"id": 101, "app_id": "ghostty", "pid": 1, "name": "term", "ws": "1", "output": "DP-3"}
_B = {"id": 102, "app_id": "firefox", "pid": 2, "name": "web", "ws": "2", "output": "DP-2"}


async def _collect(session) -> list[DesktopObservation]:
    return [o async for o in session.observations()]


def _distinct_workspaces(obs: list[DesktopObservation]) -> list[str | None]:
    """The workspace values across the stream, deduplicated in first-seen order."""
    out: list[str | None] = []
    for o in obs:
        if not out or out[-1] != o.state.workspace:
            out.append(o.state.workspace)
    return out


def _niri_session() -> NiriSession:
    frames = [
        workspaces_changed(
            ws(1, 1, name="1", output="DP-3", is_focused=True, active_window_id=101),
            ws(2, 2, name="2", output="DP-2"),  # empty target on the other output
        ),
        windows_changed(
            win(101, app_id="ghostty", pid=1, title="term"),
            win(102, app_id="firefox", pid=2, title="web"),
        ),
        {"WorkspaceActivated": {"id": 2, "focused": True}},
        {"WorkspaceActiveWindowChanged": {"workspace_id": 2, "active_window_id": 102}},
    ]
    return NiriSession(_frames_from(frames))


def _sway_session() -> SwaySession:
    before = _tree([{**_A, "focused": True}])
    after = _tree([{**_A, "focused": False}, {**_B, "focused": True}])
    events = [
        IpcEvent(
            "workspace",
            {
                "change": "focus",
                "current": {"name": "2", "output": "DP-2"},
                "old": {"name": "1", "output": "DP-3"},
            },
        ),
        IpcEvent(
            "window",
            {
                "change": "focus",
                "container": {"id": 102, "app_id": "firefox", "pid": 2, "name": "web"},
            },
        ),
    ]
    return SwaySession(_events_from(events), _get_tree_returning(before, after))


async def test_niri_and_sway_agree_on_the_cross_output_switch():
    niri = await _collect(_niri_session())
    sway = await _collect(_sway_session())

    # 1. equal neutral event-name sequence, snapshot-first on both
    names = ["snapshot", "workspace_focus", "window_focus"]
    assert [o.event for o in niri] == names
    assert [o.event for o in sway] == names

    # 2. output = DRM connector names on both, landing on DP-2
    assert niri[0].state.output == sway[0].state.output == "DP-3"
    assert niri[-1].state.output == sway[-1].state.output == "DP-2"

    # 3. matching workspace-transition shape (distinct values, in order)
    assert _distinct_workspaces(niri) == _distinct_workspaces(sway) == ["1", "2"]

    # both land focus on window B
    assert niri[-1].state.window.window_id == sway[-1].state.window.window_id == 102
