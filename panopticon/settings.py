"""User configuration: where it lives and how it is read.

Config is TOML under ``$XDG_CONFIG_HOME/panopticon``; secrets never live here
(they come from the environment). Mirrors :func:`panopticon.store.state_dir`.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    """Honour ``XDG_CONFIG_HOME`` if set; otherwise ``~/.config``. Appends ``panopticon``."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "panopticon"


def load_toml(path: Path) -> dict[str, Any]:
    """Parse ``path`` as TOML. Raises ``OSError`` or ``tomllib.TOMLDecodeError``."""
    with open(path, "rb") as fh:
        return tomllib.load(fh)
