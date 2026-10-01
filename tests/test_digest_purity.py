"""SL-006 PHASE-02 EX-1: the digest core is pure — no clock, disk, rng, env or network.

An AST tripwire like I2: it catches the ordinary ways impurity creeps in
(an ``os``/``time``/``random`` import, ``datetime.now()``), not every one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.ast_imports import imported_modules, matches_any

DIGEST = Path(__file__).resolve().parent.parent / "panopticon" / "digest"
PURE_MODULES = ("config.py", "gate.py", "select.py", "prompt.py")
IMPURE_IMPORTS = (
    "os", "pathlib", "io", "shutil", "tempfile", "fcntl", "subprocess", "time", "random",
    "secrets", "uuid", "logging", "urllib.request", "http", "ssl", "socket",
    "panopticon.fsutil", "panopticon.settings", "panopticon.store",
)  # fmt: skip
CLOCK_CALLS = ("now", "today", "utcnow")


def _impurities(source: str) -> set[str]:
    tree = ast.parse(source)
    hits = {m for m in imported_modules(tree) if matches_any(m, IMPURE_IMPORTS)}
    hits |= {
        f"{node.func.attr}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in CLOCK_CALLS
    }
    hits |= {
        f"{node.id}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in ("open", "input", "print")
    }
    return hits


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
    assert _impurities(source) == {
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
    assert _impurities((DIGEST / name).read_text(encoding="utf-8")) == set()
