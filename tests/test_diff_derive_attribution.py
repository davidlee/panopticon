"""ISS-001 regression: cross-workspace focus attributes to the *new* app.

The defect: ``diff_state`` gave a workspace/output change precedence over a
focused-window-identity change, so a cross-workspace focus switch (both change at
once) collapsed to a single ``workspace_focus`` — and ``derive_segments`` retains
the running app on ``workspace_focus``, so every segment was mis-attributed to the
snapshot-time app. Snapshot-first pure-streaming adapters (umbriel; niri on a
populated-target switch) emit exactly this single combined event, with no
corrective ``window_focus`` to follow, so the mis-attribution is permanent.

This exercises the shared contract end-to-end — ``diff_state`` emission through
``derive_segments`` attribution — producer-agnostic, mirroring the umbriel
``capture-1`` discord↔emacs bounce (both workspaces populated). The umbriel
adapter's own capture replay lands with SL-005 PHASE-02.
"""

from __future__ import annotations

from panopticon.compositor.diff import compact, diff_state
from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.schema import Event, make_event
from panopticon.segmentizer.derive import derive_segments

_OUT = "DP-3"
_DISCORD = WindowRef(1, "discord", 100, "chat")
_EMACS = WindowRef(2, "emacs", 200, "code")

# discord↔emacs bounce across two populated workspaces — every hop changes both
# the focused-window identity and the workspace at once (the coalesced case).
_BOUNCE = [
    DesktopState(_DISCORD, "DP-3:1", _OUT),
    DesktopState(_EMACS, "DP-3:17", _OUT),
    DesktopState(_DISCORD, "DP-3:1", _OUT),
    DesktopState(_EMACS, "DP-3:17", _OUT),
]


def _ts(i: int) -> str:
    return f"2026-09-21T10:00:{i:02d}+00:00"


def _encode(obs: DesktopObservation, ts: str) -> Event:
    """Mirror ``compositor.events.encode`` but with a controlled ``ts``."""
    return make_event("desktop", obs.event, ts=ts, producer="umbriel", **obs.fields)


def _stream(states: list[DesktopState]) -> tuple[list[str], list[Event]]:
    """Snapshot the first state, diff the rest — the adapter's own emission path."""
    names = ["snapshot"]
    snap = DesktopObservation("snapshot", compact(states[0].to_dict()), states[0])
    events = [_encode(snap, _ts(0))]
    prior = states[0]
    for i, state in enumerate(states[1:], start=1):
        obs = diff_state(prior, state)
        assert obs is not None
        names.append(obs.event)
        events.append(_encode(obs, _ts(i)))
        prior = state
    return names, events


def test_cross_workspace_bounce_is_window_focus_not_workspace_focus():
    """Each combined hop surfaces as ``window_focus`` — identity beats location."""
    names, _ = _stream(_BOUNCE)
    assert names == ["snapshot", "window_focus", "window_focus", "window_focus"]


def test_cross_workspace_bounce_attributes_each_segment_to_its_own_app():
    """The whole point: segments alternate discord/emacs, not all-discord."""
    _, events = _stream(_BOUNCE)
    segments = list(derive_segments(events, source="desktop", close_at=_ts(9)))
    attribution = [(s.fields["app_id"], s.fields["workspace"]) for s in segments]
    assert attribution == [
        ("discord", "DP-3:1"),
        ("emacs", "DP-3:17"),
        ("discord", "DP-3:1"),
        ("emacs", "DP-3:17"),
    ]


def test_focus_leaving_to_no_window_closes_the_segment():
    """A hop to an empty workspace (window→None) is ``window_focus`` and the
    deriver closes the running segment rather than parking the old app on the
    empty workspace (the same masking bug, defocus flavour)."""
    states = [DesktopState(_DISCORD, "DP-3:1", _OUT), DesktopState(None, "DP-3:2", _OUT)]
    names, events = _stream(states)
    assert names == ["snapshot", "window_focus"]
    segments = list(derive_segments(events, source="desktop", close_at=_ts(9)))
    # only discord's segment — nothing attributed to the empty workspace
    attribution = [(s.fields["app_id"], s.fields["workspace"]) for s in segments]
    assert attribution == [("discord", "DP-3:1")]
