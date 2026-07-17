from __future__ import annotations

import pytest

from panopticon.compositor.detect import select_client
from panopticon.compositor.sway._i3ipc import I3ipcSwayClient


def test_select_client_sway_returns_sway_client_and_producer():
    client, producer = select_client("sway")
    assert isinstance(client, I3ipcSwayClient)
    assert producer == "sway"
    assert client.producer == "sway"


def test_select_client_niri_raises_pointing_at_sl003():
    with pytest.raises(NotImplementedError, match="SL-003"):
        select_client("niri")


def test_select_client_auto_resolves_sway_when_socket_present(monkeypatch):
    monkeypatch.setenv("SWAYSOCK", "/run/user/1000/sway-ipc.sock")
    client, producer = select_client("auto")
    assert isinstance(client, I3ipcSwayClient)
    assert producer == "sway"


def test_select_client_auto_without_sway_defers_to_sl003(monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    with pytest.raises(NotImplementedError, match="SL-003"):
        select_client("auto")


def test_select_client_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown compositor"):
        select_client("wlroots")
