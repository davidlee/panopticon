# Audit SL-001: host-side git commit poller

Hand-authored close-out audit (no scaffold). Verification of the implementation
against `design.md` + `plan.toml`, plus a self-review of the diff.

## Verification — phase exit criteria

### PHASE-01 (pure core)
- EX-1 pure surface (no `os`/`subprocess`/`open`) — ✅ `segment.py` imports only
  `json` + `dataclasses`.
- EX-2 golden byte-match — ✅ `test_segment_line_byte_matches_golden_hook_output`.
- EX-3 `(repo, sha)` dedup, cross-repo no-collide — ✅
  `test_shas_in_segment_cross_repo_prefix_does_not_collide`.
- EX-4 slug variants — ✅ trailing-slash / `.git` / scp / empty→basename tests.
- VT-1/VT-2 — ✅ 19/19 green, ruff clean.

### PHASE-02 (impure shell)
- EX-1 discovery via `rev-parse`, bare/non-repo skipped, `.git`-as-file ok — ✅
  `test_discover_*`.
- EX-2 one line/commit, hook's `diff-tree` files_changed, `--branches` — ✅
  `test_poll_emits_one_line_per_commit` + differential.
- EX-3 dedup (2nd poll no-op; hook-preseeded sha skipped) — ✅
  `test_poll_second_run_is_noop`, `test_poll_skips_preseeded_sha`.
- EX-4 flock no-op when held — ✅ `test_poll_is_noop_when_lock_held`.
- EX-5 differential byte-identical across shapes — ✅ 3 `requires_hook` tests pass
  unskipped on this host (root/normal/merge/empty/no-remote/trailing-slash).
- EX-6 non-checked-out branch emitted — ✅
  `test_poll_emits_commit_on_non_checked_out_branch`.
- VT-1/VT-2 — ✅ 31 git tests / 244 full suite, ruff clean.

### PHASE-03 (ops)
- EX-1 entry point — ✅ `panopticon-git --help` works.
- EX-2 systemd oneshot + 5-min timer — ✅ `systemd/git-poller.{service,timer}`.
- EX-3 README producer + freshness-exception + ISSUE-006 follow-up note — ✅.
- VT-1 `--help` + temp-repo run — ✅ smoke: 1 emitted, rerun dedups to 0.
- VT-2 `just test`/`just lint` — ✅ 244 passed / clean (gate repaired with
  `--extra dev`).

## Drift vs design

- None material. Design §5.1 named `parse_candidates`/`shas_in_segment`/
  `segment_line` — all present with those names. `commit_fields` (author+subject
  in one call) is the design's stated NUL-split optimisation (§7), not drift.

## Self-review (diff)

- **Contract risk** is the whole slice; mitigated by *two independent* proofs
  (golden line + live differential). If the hook is ever absent at test time the
  differential silently skips — golden still guards the bytes. Acceptable;
  documented (design §9).
- **Subprocess cost**: `poll` runs 1 `git log` per repo + (2 calls × *new*
  commits). Dedup precedes the expensive calls, so steady-state cost ≈ one `git
  log` per repo per 5 min. Fine.
- **Error handling**: `_git_ok` swallows nonzero → `None`; a transiently broken
  repo yields no candidates that poll rather than aborting the whole run. Matches
  the hook's best-effort `exit 0` ethos.
- **Resource hygiene**: lock fd + segment fd both `close()`d in `finally`.
- **No parallel implementation**: rides `state_dir()` and the `RawStore`
  O_APPEND idiom; the foreign git line legitimately bypasses `Event`/`RawStore`
  (different contract), which is why those are mirrored not imported.

## Open / follow-up

- `.emacs.d` ISSUE-006 step 2 (hook retirement) — external repo, tracked in notes.
- A full `/code-review` pass was not separately run; the differential + golden
  tests + this self-review cover the correctness surface. Run `/code-review` on
  the diff if a second pair of eyes is wanted before merge.
