from __future__ import annotations

from pathlib import Path

import pytest

from panopticon.desktop_watcher.__main__ import main, parse_args

# ---- parse_args ----


def test_parse_args_defaults():
    args = parse_args([])
    assert args.compositor == "auto"
    assert args.state_dir is None
    assert args.verbose == 0


def test_parse_args_compositor_sway():
    assert parse_args(["--compositor", "sway"]).compositor == "sway"


def test_parse_args_rejects_unknown_compositor():
    with pytest.raises(SystemExit):
        parse_args(["--compositor", "wlroots"])


def test_parse_args_state_dir():
    assert parse_args(["--state-dir", "/tmp/behaviour"]).state_dir == Path("/tmp/behaviour")


def test_parse_args_help_exits():
    with pytest.raises(SystemExit) as exc:
        parse_args(["--help"])
    assert exc.value.code == 0


# ---- compositor selection (VT-1) ----


def test_main_niri_raises_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError, match="SL-003"):
        main(["--compositor", "niri", "--state-dir", str(tmp_path)])


def test_main_sway_wires_store_with_compat_alias(monkeypatch, tmp_path):
    """--compositor sway builds a RawStore(source='desktop', aliases=('sway',))
    and hands the sway client to the neutral watcher."""
    captured = {}

    def fake_run(client, store):
        captured["producer"] = client.producer
        captured["source"] = store.source
        captured["aliases"] = store.current_aliases

    monkeypatch.setattr("panopticon.desktop_watcher.__main__._run", fake_run)
    rc = main(["--compositor", "sway", "--state-dir", str(tmp_path)])
    assert rc == 0
    assert captured == {"producer": "sway", "source": "desktop", "aliases": ("sway",)}
