"""Impure shell for the host-side git-commit producer.

Polls git work trees under a dev root and appends one byte-compatible segment
line per new commit to ``segments/git-<day>.jsonl`` — the same tree the SATAN
``post-commit`` hook writes, but env-agnostic so it also captures commits made
inside bwrap jails (where the hook never fires).

This is the only module that touches git or the filesystem; all formatting is
delegated to the pure :mod:`panopticon.git_poller.segment` core. Writes use the
same atomic ``O_APPEND`` discipline as :class:`panopticon.store.RawStore`.
"""

from __future__ import annotations

import fcntl
import logging
import os
import subprocess
from pathlib import Path

from panopticon.git_poller.segment import (
    Candidate,
    parse_candidates,
    segment_line,
    shas_in_segment,
    slug_for,
)
from panopticon.store import state_dir

log = logging.getLogger("panopticon.git")

LOCK_NAME = "git-poller.lock"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_ok(repo: Path, *args: str) -> str | None:
    """Run a git command; return stripped stdout, or ``None`` on nonzero exit."""
    res = _git(repo, *args)
    if res.returncode != 0:
        log.debug(
            "git %s in %s exited %d: %s",
            " ".join(args), repo, res.returncode, res.stderr.strip(),
        )
        return None
    return res.stdout.strip()


def discover_repos(dev_root: Path) -> list[Path]:
    """Return the toplevel path of each non-bare git work tree directly under
    ``dev_root``.

    Uses ``git rev-parse`` (not a ``.git`` directory test) so linked worktrees
    whose ``.git`` is a file are handled; bare repos and non-repos are skipped.
    The returned path is git's own ``--show-toplevel`` so it matches the hook's
    ``repo`` field byte-for-byte.
    """
    if not dev_root.is_dir():
        return []
    repos: list[Path] = []
    for child in sorted(dev_root.iterdir()):
        if not child.is_dir():
            continue
        res = _git(child, "rev-parse", "--show-toplevel", "--is-bare-repository")
        if res.returncode != 0:
            continue
        out = res.stdout.split()
        if len(out) != 2 or out[1] != "false":
            continue  # bare repo or unexpected output → skip
        toplevel = Path(out[0])
        if toplevel.resolve() != child.resolve():
            continue  # toplevel climbed to an ancestor repo — child is not one
        repos.append(toplevel)
    return repos


def repo_remote(repo: Path) -> str:
    """``remote.origin.url`` or empty string (matching the hook)."""
    return _git_ok(repo, "config", "--get", "remote.origin.url") or ""


def enumerate_candidates(repo: Path, since: str) -> list[Candidate]:
    """Enumerate commits across all local heads within the ``since`` horizon.

    ``--branches`` (not ``HEAD``) captures commits on branches that aren't
    currently checked out; it deliberately excludes remote-tracking refs, which
    the push hook never saw.
    """
    out = _git_ok(
        repo, "log", "--branches", f"--since={since}", "--pretty=format:%H %h %cI"
    )
    return parse_candidates(out) if out else []


def commit_fields(repo: Path, full_sha: str) -> tuple[str, str]:
    """Return ``(author, subject)`` via one ``git log -1`` (NUL-split).

    The hook reads ``%an`` and ``%s`` in two separate calls; this folds them into
    one. Safe because of two invariants git guarantees: ``%an`` (a single header
    line) can contain no NUL — NUL is git's own field separator — so the first
    ``\\x00`` unambiguously ends the author; and ``%s`` is single-line, so the
    remainder is the whole subject.
    """
    out = _git_ok(repo, "log", "-1", "--pretty=format:%an%x00%s", full_sha) or ""
    author, _, subject = out.partition("\x00")
    return author, subject


def commit_files_changed(repo: Path, full_sha: str) -> int:
    """Count changed paths exactly as the hook does (``--root``; merges → 0)."""
    out = _git_ok(
        repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", full_sha
    )
    if not out:
        return 0
    return sum(1 for line in out.splitlines() if line)


def _append_segment(seg_path: Path, line: str) -> None:
    """Atomic single-line append (one ``O_APPEND`` write, line ≪ PIPE_BUF)."""
    seg_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(seg_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _load_day_shas(seg_path: Path, repo: str) -> set[str]:
    if not seg_path.exists():
        return set()
    return shas_in_segment(seg_path.read_text(encoding="utf-8").splitlines(), repo)


def _poll_unlocked(dev_root: Path, state_root: Path, since: str) -> int:
    segments = state_root / "segments"
    # Cache key is (day-file, repo): two repos sharing a day-file each carry
    # their own (repo, sha) set, so the second repo loads its own on-disk shas
    # rather than inheriting the first's — and each (repo, day) is read once.
    seen_by_key: dict[tuple[Path, str], set[str]] = {}
    emitted = 0

    for repo in discover_repos(dev_root):
        repo_str = str(repo)
        remote = repo_remote(repo)
        slug = slug_for(remote, repo_str)
        for cand in enumerate_candidates(repo, since):
            seg_path = segments / f"git-{cand.day}.jsonl"
            key = (seg_path, repo_str)
            if key not in seen_by_key:
                seen_by_key[key] = _load_day_shas(seg_path, repo_str)
            seen = seen_by_key[key]
            if cand.short in seen:
                continue
            author, subject = commit_fields(repo, cand.full)
            line = segment_line(
                repo=repo_str,
                slug=slug,
                remote=remote,
                sha=cand.short,
                subject=subject,
                author=author,
                files_changed=commit_files_changed(repo, cand.full),
                ts=cand.cI,
            )
            _append_segment(seg_path, line)
            seen.add(cand.short)
            emitted += 1
    return emitted


def poll(dev_root: Path, state_root: Path | None = None, *, since: str = "7.days") -> int:
    """Poll every repo under ``dev_root`` once; return the number of lines emitted.

    A non-blocking ``flock`` on ``<state_root>/git-poller.lock`` guarantees no two
    polls overlap — if a poll is already running this one is a no-op (returns 0).
    """
    root = state_root if state_root is not None else state_dir()
    root.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(root / LOCK_NAME, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("another poll holds the lock; skipping")
            return 0
        try:
            return _poll_unlocked(dev_root, root, since)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)
