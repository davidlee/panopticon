from __future__ import annotations

from panopticon.compositor.events import encode
from panopticon.compositor.model import DesktopObservation, DesktopState
from panopticon.schema import SCHEMA_VERSION, Event


def _obs(event: str, **fields) -> DesktopObservation:
    return DesktopObservation(event=event, fields=dict(fields), state=DesktopState())


# ---- encode injects source + producer only (VT-1 / INV-2) ----


def test_encode_injects_source_and_producer():
    obs = _obs("window_focus", window_id=991, app_id="firefox")
    ev = encode(obs, "sway")
    assert ev.source == "desktop"
    assert ev.event == "window_focus"
    assert ev.fields["producer"] == "sway"
    assert ev.fields["window_id"] == 991


def test_encode_is_sole_injector_source_producer_absent_from_obs_fields():
    obs = _obs("window_focus", window_id=1)
    assert "source" not in obs.fields
    assert "producer" not in obs.fields
    ev = encode(obs, "sway")
    # They appear only because encode put them there.
    assert ev.source == "desktop"
    assert ev.fields["producer"] == "sway"


def test_encode_preserves_per_event_fields_verbatim():
    obs = _obs("window_title", window_id=1, old_title="a", title="b", workspace="1")
    ev = encode(obs, "sway")
    assert ev.fields == {
        "producer": "sway",
        "window_id": 1,
        "old_title": "a",
        "title": "b",
        "workspace": "1",
    }


def test_encode_lifecycle_event_names():
    for name in ("compositor_disconnected", "compositor_reconnected"):
        ev = encode(_obs(name, reason="EOF"), "sway")
        assert ev.event == name
        assert ev.source == "desktop"
        assert ev.fields["producer"] == "sway"


# ---- round-trip through schema (VT-3) ----


def test_encoded_event_roundtrips_through_from_dict():
    obs = _obs(
        "window_focus",
        window_id=991,
        app_id="firefox",
        pid=1,
        title="x",
        workspace="1",
        output="DP-1",
    )
    ev = encode(obs, "sway")
    restored = Event.from_dict(ev.to_dict())
    assert restored == ev


def test_desktop_producer_window_id_sample_from_dict():
    d = {
        "v": SCHEMA_VERSION,
        "ts": "2026-05-19T10:00:00.000+10:00",
        "source": "desktop",
        "event": "window_focus",
        "producer": "sway",
        "window_id": 991,
    }
    ev = Event.from_dict(d)
    assert ev.source == "desktop"
    assert ev.fields["producer"] == "sway"
    assert ev.fields["window_id"] == 991
