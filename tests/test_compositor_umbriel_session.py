"""UmbrielSession + UmbrielClient over the pure projection (SL-005 PHASE-02).

The session is the impure two-mode glue between ``protocol.frames`` and the
neutral observation stream, mirroring ``NiriSession``. *Burst mode* buffers
``apply()`` until ``burst_complete`` then emits one ``snapshot`` (INV-U2),
bounded by ``burst_timeout`` (raises → disconnect, RV-005.5a). *Live mode* diffs
``to_state`` via the SHARED ``diff_state``; a new-workspace
windows-before-workspaces sequence coherence-holds (withhold + fold, no baseline
advance) until the ``workspaces`` entry lands → ONE precedence-correct
observation, bounded by ``coherence_timeout`` (raises → disconnect/reburst,
RV-005.2). No ``workspace=None`` live observation ever escapes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from panopticon.compositor.model import DesktopObservation, DesktopState, WindowRef
from panopticon.compositor.umbriel.session import UmbrielClient, UmbrielSession
from panopticon.schema import make_event
from panopticon.segmentizer.derive import derive_segments
from tests.umbriel_wire import win, windows, workspaces, ws

FIXTURES = Path(__file__).parent / "fixtures" / "umbriel"

# ---- harness -----------------------------------------------------------------


def _frames_from(events):
    def factory():
        async def gen():
            for e in events:
                yield e

        return gen()

    return factory


def _frames_then_hang(events):
    """Yield the events, then block open forever — a silent-but-open socket."""

    def factory():
        async def gen():
            for e in events:
                yield e
            await asyncio.Event().wait()  # never set — never EOFs, never yields
            yield  # pragma: no cover — unreachable, keeps this a generator

        return gen()

    return factory


async def _collect(session: UmbrielSession) -> list[DesktopObservation]:
    return [o async for o in session.observations()]


def _session(frames, **kw) -> UmbrielSession:
    return UmbrielSession(frames, **kw)


# a resolved single-window burst: window "a" active on workspace DP-3:1 "dev"
def _burst(win_over=None, ws_over=None):
    win_over = win_over or {}
    ws_over = ws_over or {}
    return [
        windows(win("a", active=True, focused=True, workspace="DP-3:1", **win_over)),
        workspaces(ws("DP-3:1", 1, name="dev", named=True, focused=True, **ws_over)),
    ]


# ---- snapshot-first + burst gate (VT-1) -------------------------------------


async def test_snapshot_emitted_only_after_burst_complete():
    obs = await _collect(_session(_frames_from(_burst())))
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state == DesktopState(
        WindowRef("a", "com.mitchellh.ghostty", 618860, "win-a"), "dev", "DP-3"
    )


async def test_partial_burst_one_family_then_eof_yields_nothing():
    obs = await _collect(_session(_frames_from([windows(win("a"))])))
    assert obs == []


async def test_empty_state_is_a_valid_snapshot():
    """INV-U2: both families but no focus → an empty snapshot, not withheld."""
    frames = [windows(), workspaces(ws("DP-3:1", 1, focused=True))]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state == DesktopState()


async def test_one_family_then_silent_raises_on_burst_timeout():
    """RV-005.5a: a socket that sends one family then goes silent-but-open must
    fail fast on the burst-completion deadline, not wait for the second forever."""
    session = _session(_frames_then_hang([windows(win("a"))]), burst_timeout=0.05)
    with pytest.raises(TimeoutError):
        await _collect(session)


# ---- live coherence hold (VT-2) ---------------------------------------------


async def test_new_workspace_hold_emits_one_window_focus_with_resolved_label():
    """A new-workspace windows-before-workspaces sequence: the incoherent windows
    frame is withheld (no None→label / suffix→label flap); the landing workspaces
    frame resolves the label → ONE window_focus (focus moved a→b)."""
    frames = _burst() + [
        # focus jumps to a NEW window "b" on a NEW workspace DP-9:99 (not yet mapped)
        windows(win("b", app_id="firefox", active=True, focused=True, workspace="DP-9:99")),
        # the workspaces entry lands → coherent
        workspaces(
            ws("DP-3:1", 1, name="dev", named=True),
            ws("DP-9:99", 5, name="mail", named=True, focused=True),
        ),
    ]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot", "window_focus"]
    landing = obs[1]
    assert landing.state.window.window_id == "b"
    assert landing.state.workspace == "mail"  # resolved label, never None or "99"
    assert landing.state.output == "DP-9"


async def test_same_window_moved_to_new_workspace_is_workspace_focus():
    """The held frame keeps the SAME window but carries it to a new workspace →
    once coherent, a same-window location relabel → workspace_focus (DL-7)."""
    frames = _burst() + [
        windows(win("a", active=True, focused=True, workspace="DP-9:99")),
        workspaces(
            ws("DP-3:1", 1, name="dev", named=True),
            ws("DP-9:99", 5, name="mail", named=True, focused=True),
        ),
    ]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot", "workspace_focus"]
    assert obs[1].state.window.window_id == "a"
    assert obs[1].state.workspace == "mail"


async def test_coherence_timeout_raises_with_no_workspace_none_emit():
    """RV-005.2 fail-safe: coherence never lands → raise → disconnect/reburst;
    NO workspace=None live observation escapes (only the snapshot preceded it)."""
    seen: list[DesktopObservation] = []
    frames = _burst() + [
        windows(win("b", active=True, focused=True, workspace="DP-9:99")),  # incoherent
    ]
    session = _session(_frames_then_hang(frames), coherence_timeout=0.05)
    with pytest.raises(TimeoutError):
        async for o in session.observations():
            seen.append(o)
    assert [o.event for o in seen] == ["snapshot"]  # nothing incoherent leaked


# ---- cross-workspace switch + derive attribution (VT-3) ---------------------


def _load(name: str) -> list[dict]:
    with (FIXTURES / name).open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _ts(i: int) -> str:
    return f"2026-09-21T10:00:{i:02d}+00:00"


def _encode(obs: DesktopObservation, ts: str):
    return make_event("desktop", obs.event, ts=ts, producer="umbriel", **obs.fields)


async def test_capture1_cross_workspace_switch_attributes_the_new_app():
    """capture-1 (discord↔emacs bounce, both workspaces populated): every hop
    changes the active window → window_focus; replayed through derive_segments the
    newly-focused app is attributed, NOT the snapshot-time ghostty (DL-7/ISS-001)."""
    obs = await _collect(_session(_frames_from(_load("capture-1.ndjson"))))
    assert obs[0].event == "snapshot"
    assert all(o.event == "window_focus" for o in obs[1:])

    events = [_encode(o, _ts(i)) for i, o in enumerate(obs)]
    segments = list(derive_segments(events, source="desktop", close_at=_ts(59)))
    apps = [s.fields["app_id"] for s in segments]
    assert apps == ["com.mitchellh.ghostty", "discord", "emacs", "discord", "emacs"]
    assert set(apps[1:]) == {"discord", "emacs"}  # not all-ghostty (the mis-attribution)


# ---- title / geometry / transient active==0 (VT-4) --------------------------


async def test_title_only_change_on_focused_window_emits_window_title():
    frames = [
        windows(win("a", active=True, focused=True, workspace="DP-3:1", title="old")),
        workspaces(ws("DP-3:1", 1, name="dev", named=True, focused=True)),
        windows(win("a", active=True, focused=True, workspace="DP-3:1", title="new")),
    ]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot", "window_title"]
    assert obs[1].state.window.title == "new"


async def test_geometry_only_snapshot_emits_nothing():
    """A move/resize re-sends the window with the same neutral fields → no emit."""
    frames = _burst() + [windows(win("a", active=True, focused=True, workspace="DP-3:1"))]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]


async def test_transient_active_zero_emits_nothing_no_flap():
    """capture-0 frame 4 shape: active momentarily empties to 0 while the window
    stays focused on the focused workspace → Tier-2 yields the same window → no emit."""
    frames = _burst() + [
        windows(win("a", active=False, focused=True, workspace="DP-3:1")),
    ]
    obs = await _collect(_session(_frames_from(frames)))
    assert [o.event for o in obs] == ["snapshot"]


# ---- client glue (EX) -------------------------------------------------------


async def test_client_producer_and_session_streams_the_snapshot(tmp_path):
    sock = str(tmp_path / "umbriel.sock")

    async def handler(reader, writer):
        await reader.readline()  # the subscribe request (no ack to send)
        for frame in _burst():
            writer.write(json.dumps(frame).encode() + b"\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(handler, path=sock)
    client = UmbrielClient(sock)
    assert client.producer == "umbriel"
    async with server:
        async with client.session() as sess:
            obs = [o async for o in sess.observations()]
    assert [o.event for o in obs] == ["snapshot"]
    assert obs[0].state.workspace == "dev"
