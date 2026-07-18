"""NiriSession + NiriClient + pure diff_state (SL-003 PHASE-02, VT-1/2/3).

The session is the impure glue between ``protocol.frames`` and the neutral
observation stream: a two-mode machine that buffers the initial burst until both
full-state events land (snapshot, DL-2 / INV-N2), then diff-emits in live mode
(D10). Overview is inert by construction (DL-6). ``diff_state`` is the pure core.
"""

from __future__ import annotations

import asyncio
import json

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.compositor.niri.session import NiriClient, NiriSession, diff_state
from tests.niri_wire import win, windows_changed, workspaces_changed, ws

# ---- harness -----------------------------------------------------------------


def _frames_from(events):
    def factory():
        async def gen():
            for e in events:
                yield e

        return gen()

    return factory


async def _collect(session: NiriSession) -> list[DesktopObservation]:
    return [o async for o in session.observations()]


# ---- pure diff_state (D10 precedence) ---------------------------------------


def test_diff_state_no_change_is_none():
    st = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3")
    assert diff_state(st, st) is None


def test_diff_state_workspace_change_is_workspace_focus():
    a = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3")
    b = DesktopState(WindowRef(1, "a", 2, "t"), "mail", "DP-2")
    obs = diff_state(a, b)
    assert obs is not None and obs.event == "workspace_focus" and obs.state == b


def test_diff_state_output_only_change_is_workspace_focus():
    a = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3")
    b = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-2")
    assert diff_state(a, b).event == "workspace_focus"


def test_diff_state_window_identity_change_is_window_focus():
    a = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3")
    b = DesktopState(WindowRef(9, "z", 3, "t"), "dev", "DP-3")
    assert diff_state(a, b).event == "window_focus"


def test_diff_state_title_only_change_is_window_title():
    a = DesktopState(WindowRef(1, "a", 2, "old"), "dev", "DP-3")
    b = DesktopState(WindowRef(1, "a", 2, "new"), "dev", "DP-3")
    assert diff_state(a, b).event == "window_title"


def test_diff_state_precedence_workspace_beats_window_and_title():
    a = DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3")
    b = DesktopState(WindowRef(9, "z", 3, "u"), "mail", "DP-2")  # every field changed
    assert diff_state(a, b).event == "workspace_focus"


def test_diff_state_fields_are_the_compacted_full_state():
    obs = diff_state(DesktopState(), DesktopState(WindowRef(1, "a", 2, "t"), "dev", "DP-3"))
    assert obs.fields == {
        "window_id": 1,
        "app_id": "a",
        "pid": 2,
        "title": "t",
        "workspace": "dev",
        "output": "DP-3",
    }


# ---- snapshot-first + burst gate (VT-1) -------------------------------------

_FOCUSED_WS = ws(4, 4, name="dev", is_focused=True, active_window_id=1)


async def test_snapshot_emitted_only_after_both_full_state_events():
    frames = [
        workspaces_changed(_FOCUSED_WS),
        windows_changed(win(1, app_id="ghostty", pid=7, title="t")),
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state == DesktopState(WindowRef(1, "ghostty", 7, "t"), "dev", "DP-3")


async def test_partial_burst_yields_nothing():
    """EOF with only one full-state event seen → the partial burst is discarded."""
    obs = await _collect(NiriSession(_frames_from([workspaces_changed(_FOCUSED_WS)])))
    assert obs == []


async def test_empty_state_is_a_valid_snapshot():
    """INV-N2: both full-state events but no focus → an empty snapshot, not withheld."""
    frames = [workspaces_changed(ws(4, 4)), windows_changed()]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state == DesktopState()


async def test_no_delta_is_emitted_before_the_snapshot():
    """A delta arriving mid-burst folds into the projection but emits nothing;
    the snapshot reflects it (active_window_id 1 → 2)."""
    frames = [
        workspaces_changed(_FOCUSED_WS),
        {"WorkspaceActiveWindowChanged": {"workspace_id": 4, "active_window_id": 2}},
        windows_changed(win(1), win(2)),
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state.window == WindowRef(2, "firefox", 12345, "win-2")


# ---- overview inert + empty-workspace switch (VT-2) -------------------------


async def test_overview_gesture_emits_nothing():
    """DL-6: OverviewOpenedOrClosed + WindowFocusChanged{id:None} touch no tracked
    state, so the projected state is unchanged and no observation escapes."""
    frames = [
        workspaces_changed(_FOCUSED_WS),
        windows_changed(win(1)),
        {"OverviewOpenedOrClosed": {"is_open": True}},
        {"WindowFocusChanged": {"id": None}},
        {"OverviewOpenedOrClosed": {"is_open": False}},
        {"WindowFocusChanged": {"id": 1}},
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]


async def test_switch_to_empty_workspace_emits_one_workspace_focus_window_none():
    frames = [
        workspaces_changed(
            _FOCUSED_WS,
            ws(5, 5, name="mail", output="DP-2"),  # empty, another output
        ),
        windows_changed(win(1)),
        {"WorkspaceActivated": {"id": 5, "focused": True}},
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot", "workspace_focus"]
    wf = obs[1]
    assert wf.state.window is None
    assert wf.state.workspace == "mail"
    assert wf.state.output == "DP-2"


# ---- diff emission (VT-3) ---------------------------------------------------


async def test_title_only_change_on_the_focused_window_emits_window_title():
    frames = [
        workspaces_changed(_FOCUSED_WS),
        windows_changed(win(1, title="old")),
        {"WindowOpenedOrChanged": {"window": win(1, title="new")}},
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot", "window_title"]
    assert obs[1].state.window.title == "new"


async def test_no_op_window_change_emits_nothing():
    """A resize/column-move re-sends the window unchanged (same app/pid/title) →
    tracked state is identical → nothing emitted."""
    frames = [
        workspaces_changed(_FOCUSED_WS),
        windows_changed(win(1, title="t")),
        {"WindowOpenedOrChanged": {"window": win(1, title="t")}},
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]


async def test_title_change_on_an_unfocused_window_emits_nothing():
    frames = [
        workspaces_changed(_FOCUSED_WS),
        windows_changed(win(1), win(2)),
        {"WindowOpenedOrChanged": {"window": win(2, title="changed")}},
    ]
    obs = await _collect(NiriSession(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]  # window 2 is not focused


# ---- client glue (EX-3) -----------------------------------------------------


async def test_client_producer_and_session_stream_the_snapshot(tmp_path):
    sock = str(tmp_path / "niri.sock")

    async def handler(reader, writer):
        await reader.readline()  # the "EventStream" request
        writer.write(b'{"Ok":"Handled"}\n')
        for frame in (workspaces_changed(_FOCUSED_WS), windows_changed(win(1))):
            writer.write(json.dumps(frame).encode() + b"\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(handler, path=sock)
    client = NiriClient(sock)
    assert client.producer == "niri"
    async with server:
        async with client.session() as sess:
            obs = [o async for o in sess.observations()]
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state.workspace == "dev"
