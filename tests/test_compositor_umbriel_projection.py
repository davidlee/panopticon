"""Pure UmbrielProjection accumulator + to_state (SL-005 PHASE-01, VT-2/3/4/5).

Umbriel emits a full snapshot per event, so ``apply`` is snapshot-**replace**,
not a delta accumulator (design §5.2). Focus is two-tier (DL-4): Tier-1 the
unique ``active`` window (seat focus); Tier-2 the focused-workspace's focused
window when ``active`` transiently empties. ``apply`` is total and pure (INV-U1):
an unknown family or field returns an equal/updated projection, never raises.
Golden replay of both captures is the wire-fidelity guard.
"""

from __future__ import annotations

import json
from pathlib import Path

from panopticon.compositor.model import DesktopState
from panopticon.compositor.umbriel.projection import (
    UmbrielProjection,
    _pid,
)
from tests.umbriel_wire import win, windows, workspaces, ws

FIXTURES = Path(__file__).parent / "fixtures" / "umbriel"


def _apply_all(proj: UmbrielProjection, *events: dict) -> UmbrielProjection:
    for e in events:
        proj = proj.apply(e)
    return proj


def _load(name: str) -> list[dict]:
    with (FIXTURES / name).open() as f:
        return [json.loads(line) for line in f if line.strip()]


# ---- snapshot replace + burst gate (VT-2) -----------------------------------


def test_windows_event_replaces_windows():
    proj = UmbrielProjection().apply(windows(win("a"), win("b")))
    assert {w.id for w in proj.windows} == {"a", "b"}
    proj = proj.apply(windows(win("c")))  # full replace, not merge
    assert {w.id for w in proj.windows} == {"c"}


def test_workspaces_event_replaces_workspaces():
    proj = UmbrielProjection().apply(workspaces(ws("DP-3:1", 1), ws("DP-3:17", 2)))
    assert {w.id for w in proj.workspaces} == {"DP-3:1", "DP-3:17"}
    proj = proj.apply(workspaces(ws("DP-3:1", 1)))
    assert {w.id for w in proj.workspaces} == {"DP-3:1"}


def test_burst_complete_requires_both_families_either_order():
    assert not UmbrielProjection().burst_complete
    win_only = UmbrielProjection().apply(windows(win("a")))
    assert win_only.seen_windows and not win_only.burst_complete
    ws_only = UmbrielProjection().apply(workspaces(ws("DP-3:1", 1)))
    assert ws_only.seen_workspaces and not ws_only.burst_complete
    both = _apply_all(UmbrielProjection(), windows(win("a")), workspaces(ws("DP-3:1", 1)))
    assert both.burst_complete
    both_rev = _apply_all(UmbrielProjection(), workspaces(ws("DP-3:1", 1)), windows(win("a")))
    assert both_rev.burst_complete


def test_apply_unknown_family_is_inert():
    proj = UmbrielProjection().apply(windows(win("a")))
    for junk in (
        {"event": "theme", "data": [{"x": 1}]},
        {"event": "overview", "data": []},
        {"event": "windows"},  # no data key
        {"event": "windows", "data": "notalist"},
        {"not": "an event"},
        "garbage",
        123,
    ):
        after = proj.apply(junk)
        assert after == proj  # equal projection, never raises (INV-U1)


def test_apply_extra_fields_ignored():
    ev = windows({"id": "a", "app_id": "x", "pid": 1, "workspace": "", "extra": "nope"})
    proj = UmbrielProjection().apply(ev)
    assert proj.windows[0].id == "a"


# ---- _pid normalisation (VT-5, DL-9) ----------------------------------------


def test_pid_normalises_non_positive_and_bool():
    assert _pid(618860) == 618860
    assert _pid(-1) is None  # XWayland sentinel (capture-0 Spotify)
    assert _pid(0) is None
    assert _pid(None) is None
    assert _pid(True) is None  # bool excluded (type(p) is int) — never reads as pid 1
    assert _pid(False) is None


def test_to_state_pid_minus_one_becomes_none():
    proj = _apply_all(
        UmbrielProjection(),
        windows(win("s", app_id="Spotify", pid=-1, active=True, workspace="")),
    )
    assert proj.to_state().window.pid is None


# ---- _locate + DL-1 label (VT-4) --------------------------------------------


def _focused(**over):
    """A single active+focused window on DP-3:1, plus its workspace entry."""
    return _apply_all(
        UmbrielProjection(),
        windows(win("w", active=True, focused=True, workspace="DP-3:1")),
        workspaces(ws("DP-3:1", 1, focused=True, **over)),
    )


def test_named_workspace_renders_name_not_suffix():
    st = _focused(name="emacs", named=True).to_state()
    assert st.workspace == "emacs" and st.output == "DP-3"


def test_unnamed_workspace_renders_index_not_id_suffix():
    # capture-0 L2: id "DP-3:17" has index 2 / name "2" — label is the index, NOT 17.
    proj = _apply_all(
        UmbrielProjection(),
        windows(win("w", active=True, focused=True, workspace="DP-3:17")),
        workspaces(ws("DP-3:17", 2, name="2", named=False, focused=True)),
    )
    st = proj.to_state()
    assert st.workspace == "2" and st.output == "DP-3"


def test_new_workspace_join_miss_is_incoherent_output_from_prefix():
    # A window focused on a workspace id absent from the (retained) workspaces map:
    # focus_coherent False; label NOT fabricated from the suffix; output = id prefix.
    proj = _apply_all(
        UmbrielProjection(),
        workspaces(ws("DP-3:1", 1, focused=True)),
        windows(win("w", active=True, focused=True, workspace="DP-9:99")),
    )
    assert proj.burst_complete
    assert not proj.focus_coherent
    st = proj.to_state()
    assert st.workspace is None  # never the suffix
    assert st.output == "DP-9"  # the reliable id prefix


def test_pre_existing_workspace_is_coherent():
    proj = _focused(name="emacs", named=True)
    assert proj.focus_coherent


# ---- two-tier focus (VT-3, DL-4) --------------------------------------------


def test_tier1_unique_active_window_is_focus():
    proj = _apply_all(
        UmbrielProjection(),
        windows(
            win("a", app_id="ghostty", active=True, focused=True, workspace="DP-3:1"),
            win("b", app_id="discord", focused=True, workspace="DP-3:17"),
        ),
        workspaces(
            ws("DP-3:1", 1, name="emacs", named=True, focused=True),
            ws("DP-3:17", 2),
        ),
    )
    st = proj.to_state()
    assert st.window.window_id == "a" and st.window.app_id == "ghostty"


def test_tier2_fallback_on_active_zero_picks_focused_ws_focused_window():
    # capture-0 frame 4 shape: active==0, two focused windows (one per ws); Tier-2
    # takes the focused window on the focused workspace (DP-3:1 → ghostty).
    proj = _apply_all(
        UmbrielProjection(),
        windows(
            win("a", app_id="ghostty", active=False, focused=True, workspace="DP-3:1"),
            win("b", app_id="discord", active=False, focused=True, workspace="DP-3:17"),
        ),
        workspaces(
            ws("DP-3:1", 1, name="emacs", named=True, focused=True),
            ws("DP-3:17", 2),
        ),
    )
    st = proj.to_state()
    assert st.window.window_id == "a" and st.workspace == "emacs"


def test_more_than_one_active_falls_through_tier1():
    # ASM-U1: >1 active yields no unique Tier-1 pick → falls through to Tier-2.
    proj = _apply_all(
        UmbrielProjection(),
        windows(
            win("a", active=True, focused=True, workspace="DP-3:1"),
            win("b", active=True, focused=False, workspace="DP-3:17"),
        ),
        workspaces(
            ws("DP-3:1", 1, name="emacs", named=True, focused=True),
            ws("DP-3:17", 2),
        ),
    )
    # Tier-2: focused window on focused ws DP-3:1 → "a"; not an arbitrary active pick.
    assert proj.to_state().window.window_id == "a"


def test_genuine_no_focus_is_empty_state():
    proj = _apply_all(
        UmbrielProjection(),
        windows(win("a", active=False, focused=False, workspace="DP-3:1")),
        workspaces(ws("DP-3:1", 1, name="emacs", named=True, focused=True)),
    )
    assert proj.to_state() == DesktopState()
    assert proj.focus_coherent  # no-focus is coherent


def test_focused_scratchpad_window_has_no_workspace_or_output():
    # A seat-active scratchpad window (workspace "") surfaces via Tier-1 with
    # workspace/output None (DL-3); still coherent.
    proj = _apply_all(
        UmbrielProjection(),
        windows(win("s", app_id="signal", active=True, focused=True, workspace="")),
        workspaces(ws("DP-3:1", 1, focused=True)),
    )
    st = proj.to_state()
    assert st.window.window_id == "s"
    assert st.workspace is None and st.output is None
    assert proj.focus_coherent


# ---- golden replay (wire fidelity) ------------------------------------------


def test_capture0_replays_without_raising_and_resolves_focus():
    proj = UmbrielProjection()
    for i, event in enumerate(_load("capture-0.ndjson")):
        proj = proj.apply(event)
        if i == 1:
            assert proj.burst_complete  # burst = windows(L0) + workspaces(L1)
    st = proj.to_state()
    assert st.window is not None  # a real focused window at the end


def test_capture1_replays_and_lands_focus_coherently():
    # Every cross-workspace target in capture-1 is a *pre-existing* workspace, so
    # once the burst completes the retained workspaces map always resolves the
    # join — no coherence miss despite windows-before-workspaces ordering.
    proj = UmbrielProjection()
    for event in _load("capture-1.ndjson"):
        proj = proj.apply(event)
        if proj.burst_complete:
            assert proj.focus_coherent
    assert proj.to_state().window is not None
