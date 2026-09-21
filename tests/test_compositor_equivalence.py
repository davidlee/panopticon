"""Cross-compositor equivalence (SL-003 PHASE-02, VT-4, F-6).

The same user action — *switch to workspace "2" on output DP-2, landing focus on
window B* — driven through the Sway and Niri sessions must land equivalently:
snapshot-first, connector-name outputs on both, the same workspace-transition
shape, and the same final focus (window B on DP-2). This is the contract the
deriver depends on (INV-N3): two producers, one neutral vocabulary.

Intermediate-frame divergence (real, documented adapter difference). The two
adapters model the transition's middle frame differently, and after ISS-001
(``diff_state`` surfaces a focused-window-identity change as ``window_focus``
even under a simultaneous workspace change) that difference shows in the event
*name*, not just the window field:

* **niri** decomposes the switch through the empty target workspace, so the
  intermediate frame has *no* focused window → ``window_focus`` (window=None, a
  clean defocus the deriver closes on).
* **sway** keeps the prior window A visible while the workspace refocuses →
  ``workspace_focus`` (same window, new location), then focuses B →
  ``window_focus``.

So the intermediate name legitimately differs (``window_focus`` vs
``workspace_focus``); what must agree is the landing. Sway's retained-A
intermediate leaves a transient A-on-ws2 in the derived stream — a pre-existing
sway-adapter artifact, orthogonal to ISS-001 (see the slice notes).
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


async def test_niri_and_sway_cross_output_switch_land_equivalently():
    niri = await _collect(_niri_session())
    sway = await _collect(_sway_session())

    # 1. snapshot-first on both; same landing event (focus B via window_focus)
    assert niri[0].event == sway[0].event == "snapshot"
    assert niri[-1].event == sway[-1].event == "window_focus"

    # 1b. honest per-adapter sequences — the intermediate name differs by how each
    #     models the middle frame (ISS-001): niri nulls the window, sway keeps A.
    assert [o.event for o in niri] == ["snapshot", "window_focus", "window_focus"]
    assert [o.event for o in sway] == ["snapshot", "workspace_focus", "window_focus"]

    # 2. output = DRM connector names on both, landing on DP-2
    assert niri[0].state.output == sway[0].state.output == "DP-3"
    assert niri[-1].state.output == sway[-1].state.output == "DP-2"

    # 3. matching workspace-transition shape (distinct values, in order)
    assert _distinct_workspaces(niri) == _distinct_workspaces(sway) == ["1", "2"]

    # both land focus on window B
    assert niri[-1].state.window.window_id == sway[-1].state.window.window_id == 102
