from __future__ import annotations

from typing import Any

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.compositor.sway.project import IpcEvent
from panopticon.compositor.sway.session import SwaySession, map_event

EMPTY = DesktopState()


def _container(**overrides) -> dict:
    base = {
        "id": 991,
        "app_id": "firefox",
        "pid": 12345,
        "name": "MDN — Mozilla Firefox",
    }
    base.update(overrides)
    return base


# ============================================================================
# Pure mapper (map_event) — ports the old transform coverage, con_id->window_id.
# ============================================================================

# ---- window ----


def test_window_focus_emits_event_with_window_id():
    obs = map_event("window", {"change": "focus", "container": _container()}, EMPTY, {})
    assert obs is not None
    assert obs.event == "window_focus"
    assert obs.fields == {
        "window_id": 991,
        "app_id": "firefox",
        "pid": 12345,
        "title": "MDN — Mozilla Firefox",
    }
    assert obs.state.window == WindowRef(991, "firefox", 12345, "MDN — Mozilla Firefox")


def test_window_focus_takes_location_from_index_not_prior_state():
    """D5 unit: workspace/output come from the focused window's index entry."""
    prior = DesktopState(workspace="1:term", output="DP-1")
    index = {991: ("2:web", "HDMI-1")}
    obs = map_event("window", {"change": "focus", "container": _container()}, prior, index)
    assert obs is not None
    assert obs.state.workspace == "2:web"
    assert obs.state.output == "HDMI-1"
    assert obs.fields["workspace"] == "2:web"
    assert obs.fields["output"] == "HDMI-1"


def test_window_focus_unknown_container_yields_no_location():
    obs = map_event("window", {"change": "focus", "container": _container()}, EMPTY, {})
    assert obs is not None
    assert obs.state.workspace is None
    assert obs.state.output is None
    assert "workspace" not in obs.fields  # compacted away


def test_window_title_uses_old_title_from_state():
    prior = DesktopState(WindowRef(991, "firefox", 12345, "Old Title"))
    obs = map_event(
        "window",
        {"change": "title", "container": _container(name="New Title")},
        prior,
        {},
    )
    assert obs is not None
    assert obs.event == "window_title"
    assert obs.fields["old_title"] == "Old Title"
    assert obs.fields["title"] == "New Title"
    assert obs.state.window == WindowRef(991, "firefox", 12345, "New Title")


def test_window_title_drops_old_title_when_state_was_empty():
    obs = map_event("window", {"change": "title", "container": _container(name="t")}, EMPTY, {})
    assert obs is not None
    assert "old_title" not in obs.fields


def test_window_new_emits_event_without_changing_state():
    obs = map_event("window", {"change": "new", "container": _container()}, EMPTY, {})
    assert obs is not None
    assert obs.event == "window_new"
    assert obs.state == EMPTY


def test_window_close_clears_focus_when_match():
    prior = DesktopState(WindowRef(991, "firefox"))
    obs = map_event("window", {"change": "close", "container": _container()}, prior, {})
    assert obs is not None
    assert obs.event == "window_close"
    assert obs.state == EMPTY


def test_window_close_preserves_state_when_no_match():
    prior = DesktopState(WindowRef(42, "other"))
    obs = map_event("window", {"change": "close", "container": _container(id=991)}, prior, {})
    assert obs is not None
    assert obs.state == prior


def test_window_passthroughs_emit_named_events():
    for change, expected in (
        ("move", "window_move"),
        ("fullscreen_mode", "window_fullscreen_mode"),
        ("urgent", "window_urgent"),
    ):
        obs = map_event("window", {"change": change, "container": _container()}, EMPTY, {})
        assert obs is not None
        assert obs.event == expected
        assert obs.state == EMPTY


def test_unknown_window_change_returns_none():
    assert map_event("window", {"change": "mark", "container": _container()}, EMPTY, {}) is None


def test_window_xwayland_uses_class_for_app_id():
    payload = {
        "change": "focus",
        "container": {
            "id": 1,
            "window_properties": {"class": "Slack"},
            "pid": 9,
            "name": "Slack | random",
        },
    }
    obs = map_event("window", payload, EMPTY, {})
    assert obs is not None
    assert obs.fields["app_id"] == "Slack"


# ---- workspace ----


def test_workspace_focus_updates_workspace_and_output():
    payload = {
        "change": "focus",
        "current": {"name": "2:web", "output": "DP-1"},
        "old": {"name": "1:term"},
    }
    obs = map_event("workspace", payload, EMPTY, {})
    assert obs is not None
    assert obs.event == "workspace_focus"
    assert obs.fields == {
        "old_workspace": "1:term",
        "workspace": "2:web",
        "output": "DP-1",
    }
    assert obs.state.workspace == "2:web"
    assert obs.state.output == "DP-1"


def test_workspace_focus_preserves_window_state():
    prior = DesktopState(WindowRef(991, "firefox", title="t"))
    payload = {"change": "focus", "current": {"name": "3", "output": "DP-1"}, "old": {}}
    obs = map_event("workspace", payload, prior, {})
    assert obs is not None
    assert obs.state.window == WindowRef(991, "firefox", title="t")
    assert obs.state.workspace == "3"


def test_workspace_urgent_emits_event_without_state_change():
    payload = {"change": "urgent", "current": {"name": "5", "urgent": True}}
    obs = map_event("workspace", payload, EMPTY, {})
    assert obs is not None
    assert obs.event == "workspace_urgent"
    assert obs.fields == {"workspace": "5", "urgent": True}
    assert obs.state == EMPTY


def test_unknown_workspace_change_returns_none():
    assert map_event("workspace", {"change": "init"}, EMPTY, {}) is None


def test_unknown_kind_returns_none():
    assert map_event("binding", {"change": "run"}, EMPTY, {}) is None


# ============================================================================
# SwaySession orchestration — snapshot-first, structural refresh, D5.
# ============================================================================


def _tree(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a root tree from ``windows`` = [{id,app_id,pid,name,focused,ws,output}]."""
    outputs: dict[str, dict] = {}
    for w in windows:
        out = outputs.setdefault(
            w["output"], {"id": hash(w["output"]) & 0xFFFF, "type": "output",
                          "name": w["output"], "focused": False, "nodes": [],
                          "floating_nodes": []},
        )
        ws = next((n for n in out["nodes"] if n["name"] == w["ws"]), None)
        if ws is None:
            ws = {"id": hash(w["ws"]) & 0xFFFF, "type": "workspace", "name": w["ws"],
                  "focused": False, "nodes": [], "floating_nodes": []}
            out["nodes"].append(ws)
        ws["nodes"].append({
            "id": w["id"], "type": "con", "app_id": w.get("app_id"),
            "pid": w.get("pid"), "name": w.get("name"), "focused": w.get("focused", False),
        })
        if w.get("focused"):
            ws["focused"] = True
    return {"id": 1, "type": "root", "name": "root", "focused": False,
            "nodes": list(outputs.values()), "floating_nodes": []}


def _get_tree_returning(*trees):
    seq = list(trees)

    async def gt():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return gt


def _events_from(events):
    def factory():
        async def gen():
            for e in events:
                yield e

        return gen()

    return factory


async def _collect(session: SwaySession) -> list[DesktopObservation]:
    return [o async for o in session.observations()]


async def test_session_yields_snapshot_first_then_deltas():
    tree = _tree([{"id": 991, "app_id": "firefox", "pid": 1, "name": "MDN",
                   "focused": True, "ws": "2:web", "output": "DP-1"}])
    events = [IpcEvent("window", {"change": "title",
                                  "container": {"id": 991, "name": "Sway IPC — Firefox"}})]
    obs = await _collect(SwaySession(_events_from(events), _get_tree_returning(tree)))
    assert [o.event for o in obs] == ["snapshot", "window_title"]
    assert obs[0].fields["app_id"] == "firefox"
    assert obs[0].fields["window_id"] == 991
    assert obs[0].fields["workspace"] == "2:web"
    assert obs[1].fields["old_title"] == "MDN"
    assert obs[1].fields["title"] == "Sway IPC — Firefox"


async def test_session_snapshot_only_when_no_events():
    tree = _tree([{"id": 991, "app_id": "firefox", "pid": 1, "name": "MDN",
                   "focused": True, "ws": "2:web", "output": "DP-1"}])
    obs = await _collect(SwaySession(_events_from([]), _get_tree_returning(tree)))
    assert [o.event for o in obs] == ["snapshot"]


async def test_session_d5_cross_workspace_focus_uses_new_location():
    """D5 before/after: a focus crossing a workspace/output boundary reports the
    focused window's own workspace/output — from the index — not the prior state.

    Pre-fix (documented behaviour change): window_focus copied the prior state's
    workspace/output, so this focus would have reported workspace="1:term",
    output="DP-1". The projection now derives the true location.
    """
    tree = _tree([
        {"id": 991, "app_id": "ghostty", "pid": 1, "name": "term",
         "focused": True, "ws": "1:term", "output": "DP-1"},
        {"id": 992, "app_id": "slack", "pid": 2, "name": "Slack",
         "focused": False, "ws": "2:web", "output": "HDMI-1"},
    ])
    events = [IpcEvent("window", {"change": "focus",
                                  "container": {"id": 992, "app_id": "slack",
                                                "pid": 2, "name": "Slack"}})]
    obs = await _collect(SwaySession(_events_from(events), _get_tree_returning(tree)))
    focus = obs[1]
    assert focus.event == "window_focus"
    assert focus.fields["workspace"] == "2:web"   # NEW: was "1:term" pre-fix
    assert focus.fields["output"] == "HDMI-1"     # NEW: was "DP-1" pre-fix
    assert focus.fields["app_id"] == "slack"


async def test_session_structural_event_refreshes_index_for_later_focus():
    """A window created after snapshot is located correctly on a later focus,
    because window::new triggers a get_tree index refresh."""
    snapshot_tree = _tree([{"id": 991, "app_id": "firefox", "pid": 1, "name": "MDN",
                            "focused": True, "ws": "1:term", "output": "DP-1"}])
    refreshed_tree = _tree([
        {"id": 991, "app_id": "firefox", "pid": 1, "name": "MDN",
         "focused": True, "ws": "1:term", "output": "DP-1"},
        {"id": 992, "app_id": "slack", "pid": 2, "name": "Slack",
         "focused": False, "ws": "3:chat", "output": "HDMI-1"},
    ])
    con = {"id": 992, "app_id": "slack", "pid": 2, "name": "Slack"}
    events = [
        IpcEvent("window", {"change": "new", "container": con}),
        IpcEvent("window", {"change": "focus", "container": con}),
    ]
    session = SwaySession(_events_from(events), _get_tree_returning(snapshot_tree, refreshed_tree))
    obs = await _collect(session)
    assert [o.event for o in obs] == ["snapshot", "window_new", "window_focus"]
    assert obs[-1].fields["workspace"] == "3:chat"
    assert obs[-1].fields["output"] == "HDMI-1"


async def test_session_retains_output_across_title_event():
    """F9: output is retained via prior state across an event that doesn't carry it."""
    tree = _tree([{"id": 991, "app_id": "firefox", "pid": 1, "name": "MDN",
                   "focused": True, "ws": "2:web", "output": "DP-1"}])
    events = [IpcEvent("window", {"change": "title", "container": {"id": 991, "name": "x"}})]
    obs = await _collect(SwaySession(_events_from(events), _get_tree_returning(tree)))
    assert obs[-1].state.output == "DP-1"
