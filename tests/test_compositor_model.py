from __future__ import annotations

from panopticon.compositor.model import (
    DesktopObservation,
    DesktopState,
    WindowRef,
)

# ---- WindowRef ----


def test_window_ref_defaults_all_none():
    w = WindowRef()
    assert (w.window_id, w.app_id, w.pid, w.title) == (None, None, None, None)


# ---- DesktopState.to_dict (VT-4) ----


def test_to_dict_flattens_with_window_id_key():
    st = DesktopState(
        window=WindowRef(window_id=991, app_id="firefox", pid=123, title="MDN"),
        workspace="2:web",
        output="DP-1",
    )
    assert st.to_dict() == {
        "window_id": 991,
        "app_id": "firefox",
        "pid": 123,
        "title": "MDN",
        "workspace": "2:web",
        "output": "DP-1",
    }


def test_empty_state_to_dict_is_today_empty_shape():
    # The FocusState() empty shape, con_id renamed to window_id: all six keys None.
    assert DesktopState().to_dict() == {
        "window_id": None,
        "app_id": None,
        "pid": None,
        "title": None,
        "workspace": None,
        "output": None,
    }


# ---- DesktopObservation ----


def test_observation_carries_event_fields_state():
    state = DesktopState(workspace="1")
    obs = DesktopObservation(event="window_focus", fields={"window_id": 1}, state=state)
    assert obs.event == "window_focus"
    assert obs.fields == {"window_id": 1}
    assert obs.state is state
