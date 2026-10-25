"""SL-006 PHASE-02 EX-1: the digest core is pure — no clock, disk, rng, env or network.

An AST tripwire like I2: it catches the ordinary ways impurity creeps in
(an ``os``/``time``/``random`` import, ``datetime.now()``), not every one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ast_imports import impurities

DIGEST = Path(__file__).resolve().parent.parent / "panopticon" / "digest"
PURE_MODULES = ("config.py", "gate.py", "select.py", "prompt.py", "audit.py")


def test_detects_impurity():
    source = "\n".join(
        [
            "import os",
            "from pathlib import Path",
            "from time import monotonic",
            "import random",
            "from datetime import datetime",
            "x = datetime.now()",
            "open('f')",
            "from urllib.parse import urlsplit",
        ]
    )
    assert impurities(source) == {
        "os",
        "pathlib",
        "pathlib.Path",
        "time",
        "time.monotonic",
        "random",
        "now()",
        "open()",
    }


@pytest.mark.parametrize("name", PURE_MODULES)
def test_digest_core_module_is_pure(name: str):
    assert impurities((DIGEST / name).read_text(encoding="utf-8")) == set()
