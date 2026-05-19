from __future__ import annotations

from panopticon.schema import make_event
from panopticon.segmentizer.derive import derive_segments

# Timestamps share a single offset; second-resolution suffices for these cases.
T = "2026-05-19T10:{m:02d}:{s:02d}.000+10:00"


def ts(m: int, s: int = 0) -> str:
    return T.format(m=m, s=s)


def focus(t: str, app: str | None, ws: str | None):
    fields: dict = {}
    if app is not None:
        fields["app_id"] = app
    if ws is not None:
        fields["workspace"] = ws
    return make_event("sway", "window_focus", ts=t, **fields)


def snap(t: str, app: str | None, ws: str | None):
    fields: dict = {}
    if app is not None:
        fields["app_id"] = app
    if ws is not None:
        fields["workspace"] = ws
    return make_event("sway", "snapshot", ts=t, **fields)


def title(t: str, app: str, ws: str, name: str):
    return make_event("sway", "window_title", ts=t, app_id=app, workspace=ws, title=name)


def ws_focus(t: str, ws: str):
    return make_event("sway", "workspace_focus", ts=t, workspace=ws)


def disc(t: str):
    return make_event("sway", "sway_disconnected", ts=t)


def reconn(t: str):
    return make_event("sway", "sway_reconnected", ts=t)


# ---- empty / boundary ----


def test_empty_stream_yields_nothing():
    assert list(derive_segments([])) == []


def test_single_focus_without_close_yields_nothing():
    # Open segment with no close_at — refuse to fabricate an end_ts.
    assert list(derive_segments([snap(ts(0), "firefox", "1")])) == []


def test_close_at_emits_trailing_segment():
    segs = list(derive_segments([snap(ts(0), "firefox", "1")], close_at=ts(5)))
    assert len(segs) == 1
    s = segs[0]
    assert s.event == "focus_segment"
    assert s.source == "sway"
    assert s.fields["app_id"] == "firefox"
    assert s.fields["workspace"] == "1"
    assert s.fields["start_ts"] == ts(0)
    assert s.fields["end_ts"] == ts(5)
    assert s.fields["duration_s"] == 300.0


# ---- transitions ----


def test_app_change_closes_segment():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        focus(ts(2), "ghostty", "1"),
    ], close_at=ts(5)))
    assert [s.fields["app_id"] for s in segs] == ["firefox", "ghostty"]
    assert segs[0].fields["start_ts"] == ts(0)
    assert segs[0].fields["end_ts"] == ts(2)
    assert segs[0].fields["duration_s"] == 120.0
    assert segs[1].fields["start_ts"] == ts(2)
    assert segs[1].fields["end_ts"] == ts(5)


def test_workspace_change_closes_segment():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        ws_focus(ts(1), "2"),
        focus(ts(1, 1), "firefox", "2"),
    ], close_at=ts(5)))
    # ws_focus alone shifts (firefox,1) → (firefox,2); subsequent window_focus
    # confirms same tuple and does not split further.
    assert len(segs) == 2
    assert segs[0].fields == {
        "app_id": "firefox",
        "workspace": "1",
        "start_ts": ts(0),
        "end_ts": ts(1),
        "duration_s": 60.0,
    }
    assert segs[1].fields["workspace"] == "2"
    assert segs[1].fields["start_ts"] == ts(1)


def test_title_change_does_not_split():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        title(ts(1), "firefox", "1", "Foo"),
        title(ts(2), "firefox", "1", "Bar"),
    ], close_at=ts(5)))
    assert len(segs) == 1
    assert segs[0].fields["start_ts"] == ts(0)
    assert segs[0].fields["end_ts"] == ts(5)


def test_same_tuple_focus_does_not_split():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        focus(ts(2), "firefox", "1"),
    ], close_at=ts(5)))
    assert len(segs) == 1


# ---- disconnect handling ----


def test_disconnect_closes_segment_and_pauses():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        disc(ts(2)),
        reconn(ts(3)),
        snap(ts(3), "firefox", "1"),
    ], close_at=ts(5)))
    # firefox/1 0–2, pause, firefox/1 3–5.
    assert len(segs) == 2
    assert segs[0].fields["end_ts"] == ts(2)
    assert segs[1].fields["start_ts"] == ts(3)


# ---- null focus ----


def test_unfocused_state_yields_nothing():
    segs = list(derive_segments([
        snap(ts(0), None, None),
    ], close_at=ts(5)))
    assert segs == []


def test_focus_then_unfocus_then_focus():
    segs = list(derive_segments([
        snap(ts(0), "firefox", "1"),
        snap(ts(2), None, None),
        snap(ts(3), "ghostty", "1"),
    ], close_at=ts(5)))
    assert [s.fields["app_id"] for s in segs] == ["firefox", "ghostty"]
    assert segs[0].fields["end_ts"] == ts(2)
    assert segs[1].fields["start_ts"] == ts(3)
