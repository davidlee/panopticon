"""I2 tripwire: the shipped package has exactly one network module.

An AST walk, not a proof — ``asyncio.open_connection`` would evade it. It catches
the ordinary ways egress creeps in: a stray ``urllib.request`` or ``socket``
import outside ``panopticon/digest/client.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "panopticon"
NETWORK_MODULES = ("urllib.request", "http.client", "ssl", "socket")
SOLE_EGRESS = PACKAGE / "digest" / "client.py"


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every absolute module an import statement can bind, incl. ``from x import y``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _is_network(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in NETWORK_MODULES)


def _network_imports(source: str) -> set[str]:
    return {m for m in _imported_modules(ast.parse(source)) if _is_network(m)}


def test_detects_every_import_form():
    source = "\n".join(
        [
            "import socket",
            "import urllib.request",
            "from http import client",
            "from ssl import SSLContext",
            "from urllib.request import urlopen",
            "import json",
            "from urllib.parse import urlsplit",
            "from . import socket as local",
        ]
    )
    assert _network_imports(source) == {
        "socket",
        "urllib.request",
        "http.client",
        "ssl",
        "ssl.SSLContext",
        "urllib.request.urlopen",
    }


def test_only_digest_client_imports_network_modules():
    offenders = {
        str(path.relative_to(PACKAGE.parent)): sorted(hits)
        for path in sorted(PACKAGE.rglob("*.py"))
        if path != SOLE_EGRESS and (hits := _network_imports(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}
