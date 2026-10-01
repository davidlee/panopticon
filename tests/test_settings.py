"""Tests for the shared config-location and TOML loader (D3)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from panopticon.settings import config_dir, load_toml


def test_config_dir_honours_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "panopticon"


@pytest.mark.parametrize("xdg", [None, ""])
def test_config_dir_falls_back_to_dot_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg: str | None
):
    if xdg is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "panopticon"


def test_load_toml_parses_a_file(tmp_path: Path):
    path = tmp_path / "x.toml"
    path.write_text('enabled = true\n[gate]\ndeny = ["a.com"]\n', encoding="utf-8")
    assert load_toml(path) == {"enabled": True, "gate": {"deny": ["a.com"]}}


def test_load_toml_raises_on_malformed_toml(tmp_path: Path):
    path = tmp_path / "x.toml"
    path.write_text("enabled = \n", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_toml(path)
