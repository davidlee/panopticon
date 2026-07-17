"""``panopticon-sway`` — thin compatibility wrapper (SL-002 DD10/SQ4).

Retained so the historical console script keeps working; it is now an
alias for ``panopticon-desktop --compositor sway``. All behaviour (arg
parsing, the neutral watcher, the DD7 compat side-write) lives in
:mod:`panopticon.desktop_watcher.__main__`. Superseded once callers move
to ``panopticon-desktop`` (SL-004).
"""

from __future__ import annotations

import sys

from panopticon.desktop_watcher.__main__ import main as _desktop_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return _desktop_main(["--compositor", "sway", *args])


if __name__ == "__main__":
    raise SystemExit(main())
