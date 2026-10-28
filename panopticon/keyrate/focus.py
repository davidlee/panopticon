"""Pure: the focused window a key lands in, from ``current/desktop.json``'s payload.

The title is normalised at capture so a window whose title animates (a
terminal's spinner) stays one bucket.
"""

from __future__ import annotations

import unicodedata

from panopticon.keyrate.count import Window


def window_of(current: object) -> Window | None:
    """``(app_id, title)`` of the desktop watcher's current state; ``None`` if none is focused."""
    if not isinstance(current, dict):
        return None
    app_id, title = current.get("app_id"), current.get("title")
    if not isinstance(app_id, str):
        return None
    return app_id, _without_leading_symbols(title) if isinstance(title, str) else None


def _without_leading_symbols(title: str) -> str | None:
    """``title`` without a leading run of symbols (spinner glyphs) and spaces; ``None`` if empty."""
    rest = title.lstrip()
    while rest and unicodedata.category(rest[0]) == "So":
        rest = rest[1:].lstrip()
    return rest or None
