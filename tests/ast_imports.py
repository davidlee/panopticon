"""AST import census, shared by the import-boundary tripwires (I2, digest and keyrate purity)."""

from __future__ import annotations

import ast


def imported_modules(tree: ast.AST) -> set[str]:
    """Every absolute module an import statement can bind, incl. ``from x import y``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def matches_any(module: str, prefixes: tuple[str, ...]) -> bool:
    """True if ``module`` is one of ``prefixes`` or a submodule/member of one."""
    return any(module == p or module.startswith(p + ".") for p in prefixes)


IMPURE_IMPORTS = (
    "os", "pathlib", "io", "shutil", "tempfile", "fcntl", "subprocess", "time", "random",
    "secrets", "uuid", "logging", "urllib.request", "http", "ssl", "socket", "asyncio",
    "selectors", "evdev", "panopticon.fsutil", "panopticon.settings", "panopticon.store",
)  # fmt: skip
CLOCK_CALLS = ("now", "today", "utcnow")


def impurities(source: str) -> set[str]:
    """Clock, disk, rng, env, network or terminal use in ``source``: imports and calls."""
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
