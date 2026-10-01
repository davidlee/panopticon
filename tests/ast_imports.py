"""AST import census, shared by the import-boundary tripwires (I2, digest purity)."""

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
