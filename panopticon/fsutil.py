"""Shared filesystem primitives: atomic text replace and a non-blocking lock."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` (utf-8) to ``path`` via a sibling temp file and ``os.replace``.

    Creates parent directories. Readers see the old content or the new, never a
    partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[bool]:
    """Try a non-blocking ``flock(LOCK_EX)`` on ``path`` (created if absent).

    Yields whether the lock was acquired; never blocks or raises on contention.
    The lock is released on exit.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
