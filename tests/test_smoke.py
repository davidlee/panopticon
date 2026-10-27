import tomllib
from pathlib import Path

import panopticon

ROOT = Path(__file__).resolve().parent.parent


def test_version_comes_from_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert panopticon.__version__ == pyproject["project"]["version"]


def test_flake_derives_version_from_pyproject():
    flake = (ROOT / "flake.nix").read_text()
    assert 'version = "' not in flake
