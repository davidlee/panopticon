"""IMP-005: the keyrate core is pure (the tripwire of `test_digest_purity`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ast_imports import impurities

KEYRATE = Path(__file__).resolve().parent.parent / "panopticon" / "keyrate"
PURE_MODULES = ("count.py", "focus.py", "render.py")


@pytest.mark.parametrize("name", PURE_MODULES)
def test_keyrate_core_module_is_pure(name: str):
    assert impurities((KEYRATE / name).read_text(encoding="utf-8")) == set()
