from __future__ import annotations

import json
from typing import Any

from panopticon.sway_watcher.state import (
    FocusState,
    ancestor_name_of_type,
    app_id_from_container,
    find_focused,
    focus_state_from_tree,
)


def _tree(focused_app_id: str | None = "firefox",
          title: str = "MDN — Mozilla Firefox") -> dict[str, Any]:
    """A minimal three-level sway tree: root → output → workspace → con."""
    return {
        "id": 1,
        "type": "root",
        "name": "root",
        "focused": False,
        "nodes": [
            {
                "id": 2,
                "type": "output",
                "name": "DP-1",
                "focused": False,
                "nodes": [
                    {
                        "id": 3,
                        "type": "workspace",
                        "name": "2:web",
                        "focused": True,
                        "nodes": [
                            {
                                "id": 991,
                                "type": "con",
                                "app_id": focused_app_id,
                                "pid": 12345,
                                "name": title,
                                "focused": True,
                            },
                        ],
                        "floating_nodes": [],
                    },
                ],
                "floating_nodes": [],
            },
        ],
        "floating_nodes": [],
    }


def test_app_id_prefers_native():
    con = {"app_id": "firefox",
           "window_properties": {"class": "Firefox", "instance": "Navigator"}}
    assert app_id_from_container(con) == "firefox"


def test_app_id_falls_back_to_class_then_instance():
    assert (
        app_id_from_container({"window_properties": {"class": "X-Class"}}) == "X-Class"
    )
    assert (
        app_id_from_container({"window_properties": {"instance": "x-inst"}}) == "x-inst"
    )


def test_app_id_returns_none_when_unknown():
    assert app_id_from_container({}) is None
    assert app_id_from_container({"window_properties": {}}) is None


def test_find_focused_returns_deepest():
    """Sway flags every container on the focus chain — return the leaf."""
    tree = _tree()
    found = find_focused(tree)
    assert found is not None
    assert found["id"] == 991


def test_find_focused_returns_none_when_nothing_focused():
    tree = _tree()
    # Unfocus everything.
    tree["nodes"][0]["nodes"][0]["focused"] = False
    tree["nodes"][0]["nodes"][0]["nodes"][0]["focused"] = False
    assert find_focused(tree) is None


def test_find_focused_returns_workspace_when_no_window():
    tree = _tree()
    tree["nodes"][0]["nodes"][0]["nodes"] = []  # no children
    found = find_focused(tree)
    assert found is not None
    assert found["type"] == "workspace"


def test_ancestor_name_of_type_finds_workspace_and_output():
    tree = _tree()
    assert ancestor_name_of_type(tree, 991, "workspace") == "2:web"
    assert ancestor_name_of_type(tree, 991, "output") == "DP-1"


def test_ancestor_name_returns_none_for_unknown_id():
    tree = _tree()
    assert ancestor_name_of_type(tree, 9999, "workspace") is None


def test_focus_state_from_tree_builds_full_snapshot():
    state = focus_state_from_tree(_tree())
    assert state == FocusState(
        con_id=991,
        app_id="firefox",
        pid=12345,
        title="MDN — Mozilla Firefox",
        workspace="2:web",
        output="DP-1",
    )


def test_focus_state_from_tree_empty_when_nothing_focused():
    tree = _tree()
    tree["nodes"][0]["nodes"][0]["focused"] = False
    tree["nodes"][0]["nodes"][0]["nodes"][0]["focused"] = False
    assert focus_state_from_tree(tree) == FocusState()


def test_focus_state_to_dict_round_trips_through_json():
    state = focus_state_from_tree(_tree())
    payload = state.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["app_id"] == "firefox"


def test_floating_node_is_searched():
    tree = _tree()
    floater = {
        "id": 7,
        "type": "con",
        "app_id": "pavucontrol",
        "pid": 555,
        "name": "Volume Control",
        "focused": True,
    }
    workspace = tree["nodes"][0]["nodes"][0]
    workspace["nodes"][0]["focused"] = False  # un-focus the regular con
    workspace["floating_nodes"].append(floater)
    state = focus_state_from_tree(tree)
    assert state.con_id == 7
    assert state.app_id == "pavucontrol"
    assert state.workspace == "2:web"
