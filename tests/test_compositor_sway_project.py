from __future__ import annotations

import json
from typing import Any

from panopticon.compositor.model import DesktopState, WindowRef
from panopticon.compositor.sway.project import (
    ancestor_name_of_type,
    app_id_from_container,
    build_location_index,
    find_focused,
    focus_state_from_tree,
)


def _tree(
    focused_app_id: str | None = "firefox",
    title: str = "MDN — Mozilla Firefox",
) -> dict[str, Any]:
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


# ---- app_id ----


def test_app_id_prefers_native():
    con = {
        "app_id": "firefox",
        "window_properties": {"class": "Firefox", "instance": "Navigator"},
    }
    assert app_id_from_container(con) == "firefox"


def test_app_id_falls_back_to_class_then_instance():
    assert app_id_from_container({"window_properties": {"class": "X-Class"}}) == "X-Class"
    assert app_id_from_container({"window_properties": {"instance": "x-inst"}}) == "x-inst"


def test_app_id_returns_none_when_unknown():
    assert app_id_from_container({}) is None
    assert app_id_from_container({"window_properties": {}}) is None


# ---- find_focused ----


def test_find_focused_returns_deepest():
    found = find_focused(_tree())
    assert found is not None
    assert found["id"] == 991


def test_find_focused_returns_none_when_nothing_focused():
    tree = _tree()
    tree["nodes"][0]["nodes"][0]["focused"] = False
    tree["nodes"][0]["nodes"][0]["nodes"][0]["focused"] = False
    assert find_focused(tree) is None


def test_find_focused_returns_workspace_when_no_window():
    tree = _tree()
    tree["nodes"][0]["nodes"][0]["nodes"] = []
    found = find_focused(tree)
    assert found is not None
    assert found["type"] == "workspace"


# ---- ancestry ----


def test_ancestor_name_of_type_finds_workspace_and_output():
    tree = _tree()
    assert ancestor_name_of_type(tree, 991, "workspace") == "2:web"
    assert ancestor_name_of_type(tree, 991, "output") == "DP-1"


def test_ancestor_name_returns_none_for_unknown_id():
    assert ancestor_name_of_type(_tree(), 9999, "workspace") is None


# ---- focus_state_from_tree -> DesktopState (VT-3) ----


def test_focus_state_from_tree_builds_full_snapshot():
    state = focus_state_from_tree(_tree())
    assert state == DesktopState(
        window=WindowRef(
            window_id=991,
            app_id="firefox",
            pid=12345,
            title="MDN — Mozilla Firefox",
        ),
        workspace="2:web",
        output="DP-1",
    )


def test_focus_state_from_tree_empty_when_nothing_focused():
    tree = _tree()
    tree["nodes"][0]["nodes"][0]["focused"] = False
    tree["nodes"][0]["nodes"][0]["nodes"][0]["focused"] = False
    assert focus_state_from_tree(tree) == DesktopState()


def test_focus_state_to_dict_round_trips_through_json():
    payload = focus_state_from_tree(_tree()).to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["app_id"] == "firefox"
    assert payload["window_id"] == 991


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
    workspace["nodes"][0]["focused"] = False
    workspace["floating_nodes"].append(floater)
    state = focus_state_from_tree(tree)
    assert state.window is not None
    assert state.window.window_id == 7
    assert state.window.app_id == "pavucontrol"
    assert state.workspace == "2:web"


# ---- build_location_index (D5 seed, F9) ----


def test_build_location_index_maps_every_container_to_workspace_output():
    index = build_location_index(_tree())
    assert index[991] == ("2:web", "DP-1")
    # workspace and output nodes are themselves located under their own ancestry
    assert index[3] == ("2:web", "DP-1")
    assert index[2] == (None, "DP-1")


def test_build_location_index_spans_multiple_outputs():
    tree = _tree()
    tree["nodes"].append(
        {
            "id": 12,
            "type": "output",
            "name": "HDMI-1",
            "focused": False,
            "nodes": [
                {
                    "id": 13,
                    "type": "workspace",
                    "name": "3:chat",
                    "focused": False,
                    "nodes": [
                        {
                            "id": 992,
                            "type": "con",
                            "app_id": "slack",
                            "pid": 42,
                            "name": "Slack",
                            "focused": False,
                        }
                    ],
                    "floating_nodes": [],
                }
            ],
            "floating_nodes": [],
        }
    )
    index = build_location_index(tree)
    assert index[991] == ("2:web", "DP-1")
    assert index[992] == ("3:chat", "HDMI-1")
