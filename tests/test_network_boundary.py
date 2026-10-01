"""I2 tripwire: the shipped package has exactly one network module.

An AST walk, not a proof — ``asyncio.open_connection`` would evade it. It catches
the ordinary ways egress creeps in: a stray ``urllib.request`` or ``socket``
import outside ``panopticon/digest/client.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.ast_imports import imported_modules, matches_any

PACKAGE = Path(__file__).resolve().parent.parent / "panopticon"
NETWORK_MODULES = ("urllib.request", "http.client", "ssl", "socket")
SOLE_EGRESS = PACKAGE / "digest" / "client.py"


def _network_imports(source: str) -> set[str]:
    return {m for m in imported_modules(ast.parse(source)) if matches_any(m, NETWORK_MODULES)}


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
