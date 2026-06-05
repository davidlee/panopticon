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
  `test_discover_*`. ⚠️ Originally trusted `--show-toplevel` from a non-repo
  child, which climbs to an ancestor repo (the dotfiles-in-`~` case); guarded
  post-review (`toplevel.resolve() == child.resolve()`) — see "Code review round".
- EX-2 one line/commit, hook's `diff-tree` files_changed, `--branches` — ✅
  `test_poll_emits_one_line_per_commit` + differential.
- EX-3 dedup (2nd poll no-op; hook-preseeded sha skipped) — ⚠️ **single-repo
  only**. The pure `(repo, sha)` key was correct, but the shell cache discarded
  the `repo` dimension, so multi-repo same-day polling re-emitted the non-first
  repo's commits on every poll — unbounded duplicate growth, the inverse of the
  objective. The two passing tests were both single-repo and never exercised the
  broken path. Found in code review, fixed — see "Code review round" below.
- EX-4 flock no-op when held — ✅ `test_poll_is_noop_when_lock_held`.
- EX-5 differential byte-identical across shapes — ✅ 3 `requires_hook` tests pass
  unskipped on this host (root/normal/merge/empty/no-remote/trailing-slash).
- EX-6 non-checked-out branch emitted — ✅
  `test_poll_emits_commit_on_non_checked_out_branch`.
- VT-1/VT-2 — ✅ 31 git tests / 244 full suite, ruff clean.

### PHASE-03 (ops)
- EX-1 entry point — ✅ `panopticon-git --help` works.
- EX-2 systemd oneshot + 5-min timer — ✅ **deployed.** The in-repo
  `systemd/git-poller.{service,timer}` were never the live units (uninstalled);
  the service is now defined in home-manager at
  `~/flakes/modules/home/nixos/behaviour.nix` (mirroring `panopticon-segmentize`)
  — `Type=oneshot`, absolute store-path `ExecStart=${panopticon}/bin/panopticon-git`
  (the bare-name PATH risk is moot), `OnBootSec=2min` + `OnUnitActiveSec=5min` +
  `Persistent`. Verified live: `panopticon-git.service` ran `status=0/SUCCESS`,
  `TriggeredBy: panopticon-git.timer`, timer armed (next fire +5min). The
  redundant in-repo `systemd/git-poller.*` files are now dead — candidate for
  deletion.
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
- **Error handling**: `_git_ok` returns `None` on nonzero exit (now also
  `log.debug`s repo + stderr — added post-review so a silently-missing repo is
  diagnosable); a transiently broken repo yields no candidates that poll rather
  than aborting the whole run. Matches the hook's best-effort `exit 0` ethos.
- **Resource hygiene**: lock fd + segment fd both `close()`d in `finally`.
- **No parallel implementation**: rides `state_dir()` and the `RawStore`
  O_APPEND idiom; the foreign git line legitimately bypasses `Event`/`RawStore`
  (different contract), which is why those are mirrored not imported.

## Code review round (2026-06-05)

A `/code-review` pass returned **revision-required**. The self-review above
missed the headline bug because the test helper coerced segment lines to a `set`
(destroying the multiplicity a dedup bug produces) and there was no multi-repo
coverage. Green gate, broken objective. Findings + dispositions:

- 🔴 **Dedup cache dropped `repo`** (`poller.py` `_poll_unlocked`). Cache keyed
  on the day-file path alone, so the first repo to touch a shared `git-<day>`
  populated the entry and later repos inherited its sha-set, never loading their
  own → re-emit every poll. **Fixed**: key `(seg_path, repo_str)`, loaded once
  per `(repo, day)` (folds in the per-candidate reload too). Red test first:
  `test_poll_two_repos_same_day_dedup_is_stable`. Commit `808ea60`.
- 🟠 **`seg_lines` was set-blind** — the test helper that made the 🔴 invisible.
  **Fixed**: returns a `Counter`; duplicate emission now fails `==`. `808ea60`.
- 🟠 **`discover_repos` ancestor-climb** — `--show-toplevel` from a non-repo
  child resolves upward and enrolled a foreign ancestor repo. **Fixed**: require
  `toplevel.resolve() == child.resolve()`; `test_discover_skips_child_of_ancestor_repo`.
  `808ea60`.
- 🟡 **`_git_ok` silent on failure** — **Fixed**: `log.debug` repo + stderr on
  nonzero. `808ea60`.
- 🟡 **`commit_fields` one-call divergence** — packs `%an%x00%s` where the hook
  uses two calls. Correct (git guarantees `%an` has no NUL, `%s` single-line),
  but the invariant was half-stated. **Disposition (b)**: kept the one-call,
  named both invariants in the docstring. Commit `9a85651`.
- 🟡 **Differential is host-conditional** — `test_differential_*` skip when the
  real hook file is absent, so the strongest byte-parity proof runs only on
  david's host; elsewhere only the golden line guards the contract. **Accepted,
  WON'T FIX**: no CI and no second host, so vendoring the hook as a fixture would
  add a stale duplicate source-of-truth for zero coverage gain today. Revisit if
  CI ever lands.

Post-fix gate: 246 passed, ruff clean.

### Deploy-verification finding — test suite polluted the production feed

Surfaced while smoke-testing the live timer: the first real poll's feed held
rows with `repo=/tmp/.../pytest-.../dev/proj`. Root cause was **not** the poller
— the host installs `satan-git-post-commit` via a global `core.hooksPath`, so
every `git commit` the suite makes in a tmp repo fired the hook with no
`SATAN_BEHAVIOUR_DIR` override and wrote tmp-repo rows into the developer's real
`~/.local/state/behaviour/segments/git-<day>.jsonl`. ~12 rows per run,
compounding across every `just check` — 951 junk rows had accumulated across 4
day-files (29 May–5 Jun).

- **Fix** (`89d43f0`): `make_repo` sets a repo-local `core.hooksPath=/dev/null`
  (local overrides global); the differential tests exec the hook directly so
  they are unaffected. Verified: a full run now adds 0 rows to the real feed.
- **Data cleanup**: the 951 `/tmp` rows were stripped from the live feed (folder
  backed up, filtered on `"repo":"/tmp/`, verified no `/tmp` rows + dedup clean +
  all survivors legit `~/dev` / `~` / `~/notes` / `~/.emacs.d`, backup removed).
- **Lesson**: any test that runs real `git commit` on a host with a global hook
  writes to real state by default. The honest-real-git test stance (no mocks) is
  good, but it must neutralise host hooks — now baked into `make_repo`.

## Open / follow-up

- **EX-2 not done — stand up the service.** Unit files exist but are uninstalled
  / disabled / inactive (see PHASE-03 EX-2). To actually run on the 5-min timer:
  fix `ExecStart` to an absolute `panopticon-git` path (or symlink into the user
  PATH), copy the units to `~/.config/systemd/user/`, then
  `systemctl --user enable --now git-poller.timer`. Until then the poller never
  fires unattended.
- `.emacs.d` ISSUE-006 step 2 (hook retirement) — external repo, tracked in notes.
