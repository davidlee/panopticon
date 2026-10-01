"""Tests for the shared atomic-write and lock helpers (D6)."""

from __future__ import annotations

import fcntl
from pathlib import Path

from panopticon.fsutil import atomic_write_text, exclusive_lock


def test_atomic_write_text_creates_parents_and_writes_exact_content(tmp_path: Path):
    target = tmp_path / "a" / "b" / "out.json"
    atomic_write_text(target, "héllo\n")
    assert target.read_bytes() == "héllo\n".encode()
    assert sorted(p.name for p in target.parent.iterdir()) == ["out.json"]


def test_atomic_write_text_replaces_existing_content(tmp_path: Path):
    target = tmp_path / "out.txt"
    target.write_text("old and longer", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.txt"]


def test_exclusive_lock_yields_true_when_free_and_creates_the_file(tmp_path: Path):
    lock = tmp_path / "x.lock"
    with exclusive_lock(lock) as acquired:
        assert acquired is True
    assert lock.exists()


def test_exclusive_lock_yields_false_while_another_fd_holds_it(tmp_path: Path):
    lock = tmp_path / "x.lock"
    with open(lock, "w") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with exclusive_lock(lock) as acquired:
            assert acquired is False


def test_exclusive_lock_releases_on_exit(tmp_path: Path):
    lock = tmp_path / "x.lock"
    with exclusive_lock(lock) as first:
        assert first is True
        with exclusive_lock(lock) as nested:
            assert nested is False
    with exclusive_lock(lock) as again:
        assert again is True
