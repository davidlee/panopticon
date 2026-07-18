"""Pure NiriProjection accumulator + to_state (SL-003 PHASE-01, VT-1/2/4).

Focus derives from the focused workspace's ``active_window_id`` (DL-6), never
from the raw ``WindowFocusChanged`` stream. ``apply`` is total and pure
(INV-N1): an unknown variant or field returns an equal/updated projection,
never raises. Golden replay (capture 0) is the ASM-1 regression guard.
"""

from __future__ import annotations

import json
from pathlib import Path

from panopticon.compositor.model import DesktopState, WindowRef
from panopticon.compositor.niri.projection import (
    NiriProjection,
    NiriWindow,
    NiriWorkspace,
)
from tests.niri_wire import win as _win
from tests.niri_wire import windows_changed as _windows_changed
from tests.niri_wire import workspaces_changed as _workspaces_changed
from tests.niri_wire import ws as _ws

FIXTURES = Path(__file__).parent / "fixtures" / "niri"


# ---- builders ----------------------------------------------------------------


def _apply_all(proj: NiriProjection, *events: dict) -> NiriProjection:
    for e in events:
        proj = proj.apply(e)
    return proj


# ---- full-state replace ------------------------------------------------------


def test_windows_changed_replaces_windows_by_id():
    proj = NiriProjection().apply(_windows_changed(_win(1), _win(2)))
    assert set(proj.windows_by_id) == {1, 2}
    assert proj.windows_by_id[1] == NiriWindow(1, "firefox", 12345, "win-1")


def test_windows_changed_is_a_full_replace_not_a_merge():
    proj = _apply_all(
        NiriProjection(),
        _windows_changed(_win(1), _win(2)),
        _windows_changed(_win(3)),
    )
    assert set(proj.windows_by_id) == {3}


def test_workspaces_changed_sets_focused_from_is_focused():
    proj = NiriProjection().apply(_workspaces_changed(_ws(4, 4, is_focused=True), _ws(5, 5)))
    assert proj.focused_workspace_id == 4
    assert proj.workspaces_by_id[4] == NiriWorkspace(4, None, 4, "DP-3", None)


def test_workspaces_changed_no_focused_leaves_none():
    proj = NiriProjection().apply(_workspaces_changed(_ws(4, 4), _ws(5, 5)))
    assert proj.focused_workspace_id is None


# ---- deltas ------------------------------------------------------------------


def test_window_opened_or_changed_upserts():
    proj = NiriProjection().apply(_windows_changed(_win(1)))
    proj = proj.apply({"WindowOpenedOrChanged": {"window": _win(1, title="new")}})
    assert proj.windows_by_id[1].title == "new"
    proj = proj.apply({"WindowOpenedOrChanged": {"window": _win(9)}})
    assert set(proj.windows_by_id) == {1, 9}


def test_window_closed_drops_the_id():
    proj = _apply_all(
        NiriProjection(),
        _windows_changed(_win(1), _win(2)),
        {"WindowClosed": {"id": 1}},
    )
    assert set(proj.windows_by_id) == {2}


def test_window_closed_unknown_id_is_inert():
    proj = NiriProjection().apply(_windows_changed(_win(1)))
    assert proj.apply({"WindowClosed": {"id": 99}}).windows_by_id == proj.windows_by_id


def test_workspace_activated_moves_focus_when_focused():
    proj = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(4, 4, is_focused=True), _ws(5, 5)),
        {"WorkspaceActivated": {"id": 5, "focused": True}},
    )
    assert proj.focused_workspace_id == 5


def test_workspace_activated_unfocused_does_not_move():
    proj = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(4, 4, is_focused=True)),
        {"WorkspaceActivated": {"id": 5, "focused": False}},
    )
    assert proj.focused_workspace_id == 4


def test_workspace_active_window_changed_sets_per_workspace_active():
    proj = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(4, 4, is_focused=True, active_window_id=1)),
        {"WorkspaceActiveWindowChanged": {"workspace_id": 4, "active_window_id": 2}},
    )
    assert proj.workspaces_by_id[4].active_window_id == 2


def test_workspace_active_window_changed_unknown_workspace_is_inert():
    proj = NiriProjection().apply(_workspaces_changed(_ws(4, 4, is_focused=True)))
    event = {"WorkspaceActiveWindowChanged": {"workspace_id": 99, "active_window_id": 2}}
    assert proj.apply(event) == proj


def test_window_focus_changed_is_a_no_op():
    """DL-6: the raw focus stream is ignored; focus rides active_window_id."""
    before = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(4, 4, is_focused=True, active_window_id=1)),
        _windows_changed(_win(1)),
    )
    after = before.apply({"WindowFocusChanged": {"id": 99}})
    assert after == before


# ---- to_state (DL-6 transitive focus) ---------------------------------------


def test_to_state_derives_window_via_active_window_id():
    proj = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(4, 4, name="dev", is_focused=True, active_window_id=1)),
        _windows_changed(_win(1, app_id="ghostty", pid=7, title="t")),
    )
    assert proj.to_state() == DesktopState(
        window=WindowRef(1, "ghostty", 7, "t"), workspace="dev", output="DP-3"
    )


def test_to_state_unnamed_workspace_renders_index_string():
    proj = _apply_all(
        NiriProjection(),
        _workspaces_changed(_ws(51, 9, name=None, is_focused=True, active_window_id=1)),
        _windows_changed(_win(1)),
    )
    assert proj.to_state().workspace == "9"


def test_to_state_empty_focused_workspace_yields_no_window():
    """active_window_id None -> window None, workspace/output retained (DL-6)."""
    proj = NiriProjection().apply(
        _workspaces_changed(_ws(2, 2, name="emacs", is_focused=True, active_window_id=None))
    )
    st = proj.to_state()
    assert st.window is None
    assert st.workspace == "emacs"
    assert st.output == "DP-3"


def test_to_state_workspace_missing_idx_falls_back_to_id_not_none():
    """INV-N1: a workspace with neither name nor idx renders its id, never 'None'."""
    ws = _ws(7, 7, name=None, is_focused=True, active_window_id=None) | {"idx": None}
    proj = NiriProjection().apply(_workspaces_changed(ws))
    assert proj.to_state().workspace == "7"


def test_to_state_active_window_id_with_no_window_yet_is_none():
    proj = NiriProjection().apply(
        _workspaces_changed(_ws(4, 4, is_focused=True, active_window_id=1))
    )
    assert proj.to_state().window is None  # window 1 not yet in windows_by_id


def test_to_state_no_focused_workspace_is_empty():
    assert NiriProjection().apply(_windows_changed(_win(1))).to_state() == DesktopState()


# ---- totality (INV-N1) -------------------------------------------------------


def test_unknown_variant_is_ignored():
    proj = NiriProjection().apply(_windows_changed(_win(1)))
    assert proj.apply({"KeyboardLayoutsChanged": {"whatever": 1}}) == proj
    assert proj.apply({"CastsChanged": {}}) == proj
    assert proj.apply({"WindowFocusTimestampChanged": {"id": 1}}) == proj


def test_unknown_and_missing_fields_never_raise():
    proj = NiriProjection()
    # extra field on a known window; missing fields elsewhere
    proj = proj.apply(_windows_changed(_win(1, unexpected="x")))
    assert proj.windows_by_id[1].app_id == "firefox"
    assert proj.apply({"WindowsChanged": {}}) is not None  # missing 'windows'
    assert proj.apply({}) == proj.apply({})  # empty event inert
    assert proj.apply({"WindowClosed": {}}).windows_by_id == proj.windows_by_id


def test_non_dict_body_is_inert():
    """A known variant whose body is not a dict is ignored, never unpacked."""
    proj = NiriProjection().apply(_windows_changed(_win(1)))
    assert proj.apply({"WindowsChanged": "not-a-dict"}) == proj
    assert proj.apply({"WorkspaceActivated": [1, 2]}) == proj


def test_id_less_entities_are_dropped_not_raised():
    """INV-N1: a window/workspace missing its id is skipped; the rest survive."""
    proj = _apply_all(
        NiriProjection(),
        _windows_changed({"app_id": "no-id"}, _win(1)),
        _workspaces_changed({"is_focused": True}, _ws(4, 4, is_focused=True)),
    )
    assert set(proj.windows_by_id) == {1}
    assert set(proj.workspaces_by_id) == {4}
    assert proj.focused_workspace_id == 4  # the id-less focused ws did not win


def test_id_less_delta_targets_are_inert():
    """A delta whose target has no id leaves the projection untouched."""
    proj = NiriProjection().apply(_windows_changed(_win(1)))
    assert proj.apply({"WindowOpenedOrChanged": {"window": {"app_id": "x"}}}) == proj
    assert proj.apply({"WorkspaceActivated": {"focused": True}}) == proj


# ---- burst-order independence ------------------------------------------------


def test_burst_order_independent():
    ws = _ws(4, 4, name="dev", is_focused=True, active_window_id=1)
    win = _win(1, title="t")
    ws_first = _apply_all(NiriProjection(), _workspaces_changed(ws), _windows_changed(win))
    win_first = _apply_all(NiriProjection(), _windows_changed(win), _workspaces_changed(ws))
    assert ws_first.to_state() == win_first.to_state()


# ---- golden replay (VT-4, ASM-1 regression guard) ---------------------------


def test_golden_capture_replays_to_dl6_focused_window():
    """VT-4: the whole capture folds to the DL-6-derived focus, not just output.

    capture-0 was recorded to exercise the coupling: its tail drives
    ``WorkspaceActiveWindowChanged`` 106->104->106 on ws 4 (the raw
    ``WindowFocusChanged`` stream ignored), then a ``WindowOpenedOrChanged``
    mutates window 106's title. Asserting the derived ``window`` — not merely
    ``output`` — makes this an actual regression guard for active_window_id
    derivation. The ``{"Ok":"Handled"}`` ack folds in inertly (apply is total).
    """
    proj = NiriProjection()
    for line in (FIXTURES / "capture-0.ndjson").read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        proj = proj.apply(json.loads(line))  # never raises (INV-N1)
    assert proj.to_state() == DesktopState(
        window=WindowRef(106, "com.mitchellh.ghostty", 3461334, "⠐ Claude Code"),
        workspace="doctrine",
        output="DP-3",
    )
