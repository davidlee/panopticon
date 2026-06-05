# Notes SL-001: host-side git commit poller

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## What shipped

- `panopticon/git_poller/` — new producer package:
  - `segment.py` (pure): `esc`, `slug_for`, `segment_line`, `Candidate`,
    `parse_candidates`, `shas_in_segment`.
  - `poller.py` (impure shell): `discover_repos`, `enumerate_candidates`,
    `commit_fields`, `commit_files_changed`, `poll` (flock + atomic append).
  - `__main__.py`: `panopticon-git` CLI.
- `systemd/git-poller.{service,timer}` (oneshot + `OnCalendar=*:0/5`).
- `pyproject.toml` entry point; README producer/freshness-exception docs.
- Tests: `tests/test_git_segment.py` (pure, golden byte-match),
  `tests/test_git_poller.py` (real-git + differential-vs-hook).

## Durable decisions (harvested from phase sheets)

- **Byte parity by reusing the hook's exact git commands**, not reconstructing
  fields from a packed `git log`. Pinned two ways: a captured golden line
  (`test_git_segment`) and a *differential* test that runs the real hook beside
  the poller (`test_git_poller`, skip-if-hook-absent).
- **`--branches` traversal**, not `HEAD` (misses other local branches) nor
  `--all` (floods remote-tracking commits the push hook never saw).
- **Stateless `(repo, sha)` dedup** — the day-file is the dedup state. Keyed on
  `(repo, sha)` so a short-sha prefix shared across repos can't false-skip.
- **Hand-built line, not `json.dumps`** — the contract is the hook's bytes; the
  hook flattens tab→space and escapes only `\` and `"`.
- **`flock` overlap guard** closes poller-vs-poller; hook-vs-poller race is
  accepted during transition (absorbed by `(repo, sha)` dedup).

## Accepted limitations (see design §5.5)

- Never-reffed detached-HEAD commits and host-down-longer-than-`--since` are out
  of the rolling 7-day committer-date horizon.
- Multi-worktree of one repo as separate `~/dev` children → duplicate rows with
  distinct `repo`. Submodules / nested repos below `~/dev/*` out of scope.
- `files_changed` on exotic merges may diverge — informational, not used for
  windowing/keying.

## Follow-ups

- **`.emacs.d` ISSUE-006 step 2** (different repo): retire/demote
  `satan-git-post-commit` to end the double-write; reconcile its CAVEAT docs.
  Until then both writers may emit a sha — dedup absorbs it.
  **DO NOT blindly retire — coverage is not equal.** The poller scans `~/dev/*`
  only; the global hook fires on commits *anywhere* (`~`, `~/notes`,
  `~/.emacs.d` are all live in the feed and outside `~/dev`). Retiring the hook
  without first widening the poller's roots would blind the feed to every
  out-of-tree repo. Options: (a) keep the hook solely for out-of-`~/dev` repos
  and let the poller own `~/dev`; or (b) make the poller's roots configurable
  (multi-root) and retire the hook only once parity is proven. No formal
  ISSUE-006 artifact exists in satan — this note + audit.md are the record.
  Corollary already shipped here: tests must neutralise the host hook
  (`make_repo` sets repo-local `core.hooksPath=/dev/null`, `89d43f0`), else
  every `git commit` in the suite pollutes the real feed.
- **Deploy** — DONE: live via home-manager
  (`~/flakes/modules/home/nixos/behaviour.nix`), oneshot + 5-min timer,
  absolute store-path ExecStart. Verified running. The in-repo `systemd/`
  unit files were dead and have been removed (`154241f`).
- **Build gate fix** (done here, note for context): `just test`/`just lint` now
  pass `--extra dev`; previously the async `test_sway_runner` suite couldn't run.
