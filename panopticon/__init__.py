"""panopticon — local desktop-behaviour capture."""

from importlib.metadata import version

# pyproject.toml is the single source; flake.nix reads it too (CHR-003).
__version__ = version("panopticon")
