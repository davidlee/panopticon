"""Storage primitives for the raw tier of ``~/.local/state/behaviour/``.

:class:`RawStore` is producer-agnostic — the ``source`` argument
parameterises the filename, not the class. Every producer (sway,
firefox, ghostty, idle, …) uses the same store; multi-writer safety
relies on POSIX ``O_APPEND`` keeping each line atomic up to
``PIPE_BUF`` (4 KiB on Linux).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from panopticon.schema import Event


def state_dir() -> Path:
    """Resolve the panopticon state root.

    Honours ``XDG_STATE_HOME`` if set; otherwise falls back to
    ``~/.local/state``. Appends the ``behaviour`` segment that all
    panopticon producers share.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "behaviour"


class RawStore:
    """Per-source per-day JSONL writer + atomic current-state snapshot."""

    def __init__(
        self,
        source: str,
        root: Path | str | None = None,
    ) -> None:
        self.source = source
        self.root = Path(root) if root else state_dir()
        self._fd: int | None = None
        self._current_day: str | None = None

    def path_for(self, day: str) -> Path:
        return self.root / "raw" / f"{self.source}-{day}.jsonl"

    def _current_path_for(self, name: str) -> Path:
        return self.root / "current" / f"{name}.json"

    @property
    def current_path(self) -> Path:
        return self._current_path_for(self.source)

    def write(self, event: Event) -> None:
        """Append ``event`` to the appropriate per-day file, rotating if needed."""
        day = event.ts[:10]
        if day != self._current_day:
            self._open(day)
        assert self._fd is not None
        line = (event.to_json_line() + "\n").encode("utf-8")
        os.write(self._fd, line)

    def write_current(self, payload: dict[str, Any]) -> None:
        """Atomically replace ``current/<source>.json`` with ``payload``.

        Consumers polling the current-state file never see a partial
        write; the rename is atomic on the same filesystem.
        """
        self._write_current_file(self.source, payload)

    def _write_current_file(self, name: str, payload: dict[str, Any]) -> None:
        target = self._current_path_for(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)
        os.replace(tmp, target)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            self._current_day = None

    def __enter__(self) -> RawStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _open(self, day: str) -> None:
        if self._fd is not None:
            os.close(self._fd)
        path = self.path_for(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(
            path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
            0o644,
        )
        self._current_day = day
