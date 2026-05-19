from __future__ import annotations

from panopticon.sway_watcher.events import (
    snapshot_event,
    sway_disconnected_event,
    sway_reconnected_event,
    transform,
)
from panopticon.sway_watcher.state import FocusState

EMPTY = FocusState()


def _container(**overrides) -> dict:
    base = {
        "id": 991,
        "app_id": "firefox",
        "pid": 12345,
        "name": "MDN — Mozilla Firefox",
    }
    base.update(overrides)
    return base


# ---- window ----


def test_window_focus_emits_event_and_updates_state():
    ev, state = transform("window", {"change": "focus", "container": _container()}, EMPTY)
    assert ev is not None
    assert ev.event == "window_focus"
    assert ev.fields == {
        "con_id": 991,
        "app_id": "firefox",
        "pid": 12345,
        "title": "MDN — Mozilla Firefox",
    }
    assert state.con_id == 991
    assert state.app_id == "firefox"


def test_window_focus_preserves_workspace_and_output():
    prior = FocusState(workspace="2:web", output="DP-1")
    _, state = transform(
        "window", {"change": "focus", "container": _container()}, prior
    )
    assert state.workspace == "2:web"
    assert state.output == "DP-1"


def test_window_title_uses_old_title_from_state():
    prior = FocusState(con_id=991, app_id="firefox", pid=12345, title="Old Title")
    ev, state = transform(
        "window",
        {"change": "title", "container": _container(name="New Title")},
        prior,
    )
    assert ev is not None
    assert ev.event == "window_title"
    assert ev.fields["old_title"] == "Old Title"
    assert ev.fields["title"] == "New Title"
    assert state.title == "New Title"
    assert state.con_id == 991  # other fields untouched


def test_window_title_drops_old_title_when_state_was_empty():
    ev, _ = transform(
        "window",
        {"change": "title", "container": _container(name="t")},
        EMPTY,
    )
    assert ev is not None
    assert "old_title" not in ev.fields


def test_window_new_emits_event_without_changing_state():
    ev, state = transform("window", {"change": "new", "container": _container()}, EMPTY)
    assert ev is not None
    assert ev.event == "window_new"
    assert state == EMPTY


def test_window_close_emits_event_and_clears_focus_when_match():
    prior = FocusState(con_id=991, app_id="firefox")
    ev, state = transform(
        "window", {"change": "close", "container": _container()}, prior
    )
    assert ev is not None
    assert ev.event == "window_close"
    assert state == EMPTY


def test_window_close_preserves_state_when_no_match():
    prior = FocusState(con_id=42, app_id="other")
    _, state = transform(
        "window", {"change": "close", "container": _container(id=991)}, prior
    )
    assert state == prior


def test_window_passthroughs_emit_named_events():
    for change, expected in (
        ("move", "window_move"),
        ("fullscreen_mode", "window_fullscreen_mode"),
        ("urgent", "window_urgent"),
    ):
        ev, state = transform(
            "window", {"change": change, "container": _container()}, EMPTY
        )
        assert ev is not None
        assert ev.event == expected
        assert state == EMPTY


def test_unknown_window_change_returns_none():
    ev, state = transform(
        "window", {"change": "mark", "container": _container()}, EMPTY
    )
    assert ev is None
    assert state == EMPTY


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
    ev, _ = transform("window", payload, EMPTY)
    assert ev is not None
    assert ev.fields["app_id"] == "Slack"


# ---- workspace ----


def test_workspace_focus_updates_workspace_and_output():
    payload = {
        "change": "focus",
        "current": {"name": "2:web", "output": "DP-1"},
        "old": {"name": "1:term"},
    }
    ev, state = transform("workspace", payload, EMPTY)
    assert ev is not None
    assert ev.event == "workspace_focus"
    assert ev.fields == {
        "old_workspace": "1:term",
        "workspace": "2:web",
        "output": "DP-1",
    }
    assert state.workspace == "2:web"
    assert state.output == "DP-1"


def test_workspace_focus_preserves_window_state():
    prior = FocusState(con_id=991, app_id="firefox", title="t")
    payload = {
        "change": "focus",
        "current": {"name": "3", "output": "DP-1"},
        "old": {},
    }
    _, state = transform("workspace", payload, prior)
    assert state.con_id == 991
    assert state.title == "t"
    assert state.workspace == "3"


def test_workspace_urgent_emits_event_without_state_change():
    payload = {"change": "urgent", "current": {"name": "5", "urgent": True}}
    ev, state = transform("workspace", payload, EMPTY)
    assert ev is not None
    assert ev.event == "workspace_urgent"
    assert ev.fields == {"workspace": "5", "urgent": True}
    assert state == EMPTY


def test_unknown_workspace_change_returns_none():
    ev, state = transform("workspace", {"change": "init"}, EMPTY)
    assert ev is None
    assert state == EMPTY


# ---- other kinds ----


def test_unknown_kind_returns_none():
    ev, state = transform("binding", {"change": "run"}, EMPTY)
    assert ev is None
    assert state == EMPTY


# ---- synthetic events ----


def test_snapshot_event_drops_none_fields():
    state = FocusState(con_id=991, app_id="firefox", title="t")
    ev = snapshot_event(state)
    assert ev.event == "snapshot"
    assert ev.fields == {"con_id": 991, "app_id": "firefox", "title": "t"}


def test_snapshot_event_empty_state():
    ev = snapshot_event(EMPTY)
    assert ev.event == "snapshot"
    assert ev.fields == {}


def test_sway_disconnected_with_and_without_reason():
    with_reason = sway_disconnected_event("EOF")
    without = sway_disconnected_event()
    assert with_reason.event == "sway_disconnected"
    assert with_reason.fields == {"reason": "EOF"}
    assert without.fields == {}


def test_sway_reconnected_event_shape():
    ev = sway_reconnected_event()
    assert ev.event == "sway_reconnected"
    assert ev.fields == {}
