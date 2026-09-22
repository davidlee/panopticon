"""Compositor detection — D7 connect-validated resolution (SL-003 PHASE-03, VT-1).

``select_client`` maps ``auto|sway|niri`` to a ``(client, producer)`` pair.
``auto`` probes each set socket var (connect-validated, not env presence — the
RV-001 F-1 stand-in is retired), preferring niri when both connect (DL-4). The
probes are monkeypatched here so no live compositor is needed and startup stays
bounded (F-5).
"""

from __future__ import annotations

import pytest

from panopticon.compositor import detect
from panopticon.compositor.detect import select_client
from panopticon.compositor.niri.session import NiriClient
from panopticon.compositor.sway._i3ipc import I3ipcSwayClient
from panopticon.compositor.umbriel.session import UmbrielClient

_NIRI_SOCK = "/run/user/1000/niri.sock"
_SWAY_SOCK = "/run/user/1000/sway-ipc.sock"
_UMBRIEL_SOCK = "/run/user/1000/umbriel.sock"


@pytest.fixture(autouse=True)
def _clear_sockets(monkeypatch):
    """Each test declares its own socket environment from a clean slate.

    Clears umbriel's derivation vars too, so the niri/sway tests never
    accidentally auto-probe umbriel from a leaked host ``$XDG_RUNTIME_DIR`` /
    ``$WAYLAND_DISPLAY`` (behaviour-preservation of the pre-umbriel suite)."""
    for var in ("NIRI_SOCKET", "SWAYSOCK", "UMBRIEL_SOCKET", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(var, raising=False)


def _stub_probes(monkeypatch, *, niri: bool, sway: bool, umbriel: bool = False):
    monkeypatch.setattr(detect, "_probe_niri", lambda _sock: niri)
    monkeypatch.setattr(detect, "_probe_sway", lambda _sock: sway)
    monkeypatch.setattr(detect, "_probe_umbriel", lambda _sock: umbriel)


def test_select_client_sway_returns_sway_client_and_producer():
    client, producer = select_client("sway")
    assert isinstance(client, I3ipcSwayClient)
    assert producer == "sway"
    assert client.producer == "sway"


def test_select_client_niri_returns_niri_client_from_env(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    client, producer = select_client("niri")
    assert isinstance(client, NiriClient)
    assert producer == "niri"
    assert client.producer == "niri"


def test_select_client_niri_without_socket_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="NIRI_SOCKET"):
        select_client("niri")


def test_select_client_auto_both_connect_prefers_niri(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    _stub_probes(monkeypatch, niri=True, sway=True)
    client, producer = select_client("auto")
    assert isinstance(client, NiriClient)  # DL-4: niri wins, not list-order
    assert producer == "niri"


def test_select_client_auto_niri_only_connect_resolves_niri(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    _stub_probes(monkeypatch, niri=True, sway=False)
    client, producer = select_client("auto")
    assert isinstance(client, NiriClient)
    assert producer == "niri"


def test_select_client_auto_sway_only_connect_resolves_sway(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    _stub_probes(monkeypatch, niri=False, sway=True)
    client, producer = select_client("auto")
    assert isinstance(client, I3ipcSwayClient)
    assert producer == "sway"


def test_select_client_auto_none_connect_raises_listing_what_was_tried(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    _stub_probes(monkeypatch, niri=False, sway=False)
    with pytest.raises(RuntimeError) as exc:
        select_client("auto")
    msg = str(exc.value)
    assert "NIRI_SOCKET" in msg and "SWAYSOCK" in msg  # lists what was tried


def test_select_client_auto_no_sockets_set_raises(monkeypatch):
    _stub_probes(monkeypatch, niri=True, sway=True)  # never consulted — nothing set
    with pytest.raises(RuntimeError):
        select_client("auto")


def test_select_client_auto_skips_probe_for_unset_socket(monkeypatch):
    """Only the set socket var is probed; an unset one is never consulted."""
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)

    def _niri_boom(_sock):
        raise AssertionError("niri must not be probed when NIRI_SOCKET is unset")

    monkeypatch.setattr(detect, "_probe_niri", _niri_boom)
    monkeypatch.setattr(detect, "_probe_sway", lambda _sock: True)
    client, producer = select_client("auto")
    assert isinstance(client, I3ipcSwayClient)
    assert producer == "sway"


def test_select_client_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown compositor"):
        select_client("wlroots")


# ---- umbriel (SL-005 PHASE-03, VT-1) ----------------------------------------


def test_select_client_umbriel_explicit_from_env(monkeypatch):
    monkeypatch.setenv("UMBRIEL_SOCKET", _UMBRIEL_SOCK)
    client, producer = select_client("umbriel")
    assert isinstance(client, UmbrielClient)
    assert producer == "umbriel"
    assert client.producer == "umbriel"


def test_select_client_umbriel_derived_from_xdg_and_display(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    client, producer = select_client("umbriel")
    assert isinstance(client, UmbrielClient)
    assert producer == "umbriel"


def test_select_client_umbriel_unresolvable_env_raises(monkeypatch):
    """Explicit umbriel with neither $UMBRIEL_SOCKET nor derivation vars → an
    actionable error (never a fabricated .../umbriel-None.sock)."""
    with pytest.raises(RuntimeError, match="UMBRIEL_SOCKET"):
        select_client("umbriel")


def test_select_client_auto_reaches_umbriel_when_only_it_connects(monkeypatch):
    monkeypatch.setenv("UMBRIEL_SOCKET", _UMBRIEL_SOCK)
    _stub_probes(monkeypatch, niri=False, sway=False, umbriel=True)
    client, producer = select_client("auto")
    assert isinstance(client, UmbrielClient)
    assert producer == "umbriel"


def test_select_client_auto_three_way_tie_prefers_niri(monkeypatch):
    monkeypatch.setenv("NIRI_SOCKET", _NIRI_SOCK)
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    monkeypatch.setenv("UMBRIEL_SOCKET", _UMBRIEL_SOCK)
    _stub_probes(monkeypatch, niri=True, sway=True, umbriel=True)
    client, producer = select_client("auto")
    assert isinstance(client, NiriClient)  # DL-8: niri > sway > umbriel
    assert producer == "niri"


def test_select_client_auto_umbriel_after_sway_when_both_reachable(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", _SWAY_SOCK)
    monkeypatch.setenv("UMBRIEL_SOCKET", _UMBRIEL_SOCK)
    _stub_probes(monkeypatch, niri=False, sway=True, umbriel=True)
    client, producer = select_client("auto")
    assert isinstance(client, I3ipcSwayClient)  # sway ahead of umbriel
    assert producer == "sway"


def test_select_client_auto_derived_socket_ineligible_unless_both_env_set(monkeypatch):
    """Auto must skip umbriel when the derived path can't be formed without a
    None — here only XDG_RUNTIME_DIR is set, so umbriel is never probed."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")  # WAYLAND_DISPLAY unset

    def _umbriel_boom(_sock):
        raise AssertionError("umbriel must not be probed when its socket can't resolve")

    monkeypatch.setattr(detect, "_probe_niri", lambda _sock: False)
    monkeypatch.setattr(detect, "_probe_sway", lambda _sock: False)
    monkeypatch.setattr(detect, "_probe_umbriel", _umbriel_boom)
    with pytest.raises(RuntimeError):
        select_client("auto")


def test_select_client_auto_derived_socket_eligible_when_both_env_set(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    _stub_probes(monkeypatch, niri=False, sway=False, umbriel=True)
    client, producer = select_client("auto")
    assert isinstance(client, UmbrielClient)
    assert producer == "umbriel"
