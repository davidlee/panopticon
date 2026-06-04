"""Impure-shell tests for the git poller (PHASE-02).

Honest tests: real ``git`` against real temp repos — no subprocess mocks. The
DIFFERENTIAL tests additionally run the *real* shell hook beside the poller and
assert byte-identical segment lines; they skip where the hook file is absent
(byte parity is still pinned by ``test_git_segment``'s golden line).
"""

from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

import pytest

from panopticon.git_poller.__main__ import main, parse_args
from panopticon.git_poller.poller import discover_repos, poll
from panopticon.git_poller.segment import segment_line

HOOK = Path("/home/david/.emacs.d/satan/bin/satan-git-post-commit")
requires_hook = pytest.mark.skipif(not HOOK.exists(), reason="real hook absent")


# ---- helpers ----


def _run(args: list[str], cwd: Path, env: dict | None = None) -> str:
    res = subprocess.run(
        args, cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return res.stdout


def make_repo(path: Path, remote: str | None = None) -> Path:
    path.mkdir(parents=True)
    _run(["git", "init", "-q"], path)
    _run(["git", "config", "user.name", "Dev Tester"], path)
    _run(["git", "config", "user.email", "dev@test.co"], path)
    if remote is not None:
        _run(["git", "remote", "add", "origin", remote], path)
    return path


def commit(repo: Path, msg: str, *, allow_empty: bool = False, write: dict | None = None) -> str:
    for name, content in (write or {}).items():
        (repo / name).write_text(content)
    if write:
        _run(["git", "add", "-A"], repo)
    args = ["git", "commit", "-q", "-m", msg]
    if allow_empty:
        args.append("--allow-empty")
    _run(args, repo)
    return _run(["git", "rev-parse", "--short", "HEAD"], repo).strip()


def run_hook(repo: Path, hook_state: Path) -> None:
    import os

    env = dict(os.environ, SATAN_BEHAVIOUR_DIR=str(hook_state))
    subprocess.run(["sh", str(HOOK)], cwd=repo, env=env, check=True)


def seg_lines(state: Path) -> set[str]:
    d = state / "segments"
    out: set[str] = set()
    if d.is_dir():
        for f in d.glob("git-*.jsonl"):
            out |= {ln for ln in f.read_text().splitlines() if ln.strip()}
    return out


def default_branch(repo: Path) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()


# ---- discovery ----


def test_discover_finds_worktree_skips_non_repo(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    repo = make_repo(dev / "real")
    commit(repo, "c1", write={"a.txt": "x"})
    (dev / "not-a-repo").mkdir()
    (dev / "loose-file").write_text("hi")

    found = discover_repos(dev)
    top = _run(["git", "rev-parse", "--show-toplevel"], repo).strip()
    assert found == [Path(top)]


def test_discover_skips_bare_repo(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(dev / "bare.git")], check=True)
    assert discover_repos(dev) == []


# ---- poll basics + dedup ----


def test_poll_emits_one_line_per_commit(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj", remote="https://github.com/foo/proj.git")
    commit(repo, "c1", write={"a.txt": "x"})
    commit(repo, "c2", write={"b.txt": "y"})

    n = poll(dev, state, since="50.years")
    lines = seg_lines(state)
    assert n == 2
    assert len(lines) == 2
    assert all('"slug":"proj"' in ln for ln in lines)


def test_poll_second_run_is_noop(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj")
    commit(repo, "c1", write={"a.txt": "x"})

    assert poll(dev, state, since="50.years") == 1
    before = seg_lines(state)
    assert poll(dev, state, since="50.years") == 0
    assert seg_lines(state) == before


def test_poll_skips_preseeded_sha(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj")
    sha = commit(repo, "c1", write={"a.txt": "x"})
    top = _run(["git", "rev-parse", "--show-toplevel"], repo).strip()
    cI = _run(["git", "log", "-1", "--pretty=format:%cI"], repo).strip()

    seg = state / "segments" / f"git-{cI[:10]}.jsonl"
    seg.parent.mkdir(parents=True)
    seg.write_text(
        segment_line(repo=top, slug="proj", remote="", sha=sha, subject="preseed",
                     author="someone-else", files_changed=9, ts=cI) + "\n"
    )

    assert poll(dev, state, since="50.years") == 0  # sha already present
    assert seg_lines(state) == {ln for ln in seg.read_text().splitlines() if ln}


def test_poll_emits_commit_on_non_checked_out_branch(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj")
    commit(repo, "base", write={"a.txt": "x"})
    main = default_branch(repo)
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    feat_sha = commit(repo, "feature work", write={"f.txt": "z"})
    _run(["git", "checkout", "-q", main], repo)  # feature not checked out

    poll(dev, state, since="50.years")
    assert any(f'"sha":"{feat_sha}"' in ln for ln in seg_lines(state))


# ---- flock overlap guard ----


def test_poll_is_noop_when_lock_held(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj")
    commit(repo, "c1", write={"a.txt": "x"})

    state.mkdir(parents=True)
    lock = open(state / "git-poller.lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert poll(dev, state, since="50.years") == 0
        assert seg_lines(state) == set()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


# ---- DIFFERENTIAL: real hook vs poller, byte-identical lines ----


@requires_hook
def test_differential_shapes_with_remote(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    hook_state, poller_state = tmp_path / "hook", tmp_path / "poller"
    repo = make_repo(dev / "proj", remote="https://github.com/foo/proj.git")

    commit(repo, "root", write={"a.txt": "x", "b.txt": "y"})  # root: files count
    run_hook(repo, hook_state)
    commit(repo, 'normal "quoted" \\and tab\there', write={"c.txt": "z"})
    run_hook(repo, hook_state)
    commit(repo, "empty one", allow_empty=True)
    run_hook(repo, hook_state)

    main = default_branch(repo)
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    commit(repo, "on feature", write={"f.txt": "w"})
    run_hook(repo, hook_state)
    _run(["git", "checkout", "-q", main], repo)
    _run(["git", "merge", "--no-ff", "-m", "merge feature", "feature"], repo)
    run_hook(repo, hook_state)

    poll(dev, poller_state, since="50.years")
    assert seg_lines(poller_state) == seg_lines(hook_state)


@requires_hook
def test_differential_trailing_slash_remote(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    hook_state, poller_state = tmp_path / "hook", tmp_path / "poller"
    repo = make_repo(dev / "proj", remote="https://github.com/foo/bar-repo.git/")
    commit(repo, "c1", write={"a.txt": "x"})
    run_hook(repo, hook_state)

    poll(dev, poller_state, since="50.years")
    lines = seg_lines(poller_state)
    assert lines == seg_lines(hook_state)
    assert all('"slug":"bar-repo"' in ln for ln in lines)


# ---- CLI ----


def test_parse_args_defaults() -> None:
    ns = parse_args([])
    assert ns.dev_root == Path.home() / "dev"
    assert ns.since == "7.days"
    assert ns.state_dir is None


def test_main_polls_dev_root(tmp_path: Path) -> None:
    dev, state = tmp_path / "dev", tmp_path / "state"
    dev.mkdir()
    repo = make_repo(dev / "proj")
    commit(repo, "c1", write={"a.txt": "x"})

    rc = main(["--dev-root", str(dev), "--state-dir", str(state), "--since", "50.years"])
    assert rc == 0
    assert len(seg_lines(state)) == 1


@requires_hook
def test_differential_no_remote(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    hook_state, poller_state = tmp_path / "hook", tmp_path / "poller"
    repo = make_repo(dev / "solo")  # no origin
    commit(repo, "c1", write={"a.txt": "x"})
    run_hook(repo, hook_state)

    poll(dev, poller_state, since="50.years")
    lines = seg_lines(poller_state)
    assert lines == seg_lines(hook_state)
    assert all('"slug":"solo","remote":""' in ln for ln in lines)
