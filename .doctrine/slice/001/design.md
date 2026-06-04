# Design SL-001: host-side git commit poller

## 1. Design Problem

Capture commits across the user's repos into the panopticon segments tree —
including commits made by bwrap-jailed agents — and present them to the SATAN
evidence consumer in the exact byte format the existing `post-commit` hook emits,
without changing that consumer.

## 2. Current State

- Producers live as packages under `panopticon/` (`sway_watcher`, `segmentizer`,
  `firefox_host`, `ingest`), exposed as `[project.scripts]` entry points and run
  by systemd units in `systemd/`.
- `store.state_dir()` resolves `$XDG_STATE_HOME/behaviour` (or
  `~/.local/state/behaviour`). `RawStore` writes the **raw** tier; `segmentizer`
  batches `raw/ → segments/` nightly via `segmentizer.timer`.
- Panopticon's own segments are `Event` JSON lines (`v/ts/source/event` + fields).
- The git feed is **foreign**: a flat object, no `Event` envelope, written
  straight to `segments/git-<day>.jsonl` by `satan-git-post-commit`. It does not
  pass through `segmentizer`. The hook misses jailed commits (its prerequisites
  aren't present inside bwrap).
- `segmentizer.retention.enforce` sweeps `segments/*` generically by trailing
  date at 90 days — `git-<day>.jsonl` is aged out for free; no `git` source
  wiring is required in `_SOURCES` / `_SEGMENT_PREFIX_FOR_RAW`. (Caveat: this only
  runs if `panopticon-segmentize` keeps running — a documented dependency, not the
  poller's job.)

## 3. Forces & Constraints

- **Hard byte contract.** Output must match `satan-git-post-commit` field-for-
  field (order, escaping, `files_changed`, slug). The `.el` consumer string-parses
  it; divergence forks the `project:<slug>` percept handle or mis-parses.
- **Env-agnostic.** Must run on the host and see jailed-agent commits — hence a
  poller over `git log`, not a push hook.
- **Freshness.** Commits must surface within a poll interval; write directly to
  `segments/`, not via the nightly batch.
- **pure/imperative split** (house rule): no git/disk in the pure layer. The git
  subprocess + filesystem live in a thin shell; parsing/formatting are pure.
- **Sealed sandbox.** Do not mount segments into the jail.
- **Co-existence.** The hook still runs; both may write the same sha until the
  `.emacs.d` retirement lands → dedup by `(repo, sha)` is mandatory.

## 4. Guiding Principles

- The segment files **are** the dedup state. No separate cursor/`seen.json` to
  persist, corrupt, or reconcile — fewer moving parts, self-healing.
- Replicate the hook's byte behaviour by **reusing the hook's exact git commands**
  per commit, not by reconstructing equivalents. Parity by construction, proven by
  a differential test that runs the real hook beside the poller.
- Cheap-first: one `git log` per repo to enumerate candidates; expensive per-commit
  commands run only for commits not already emitted.

## 5. Proposed Design

New package `panopticon/git_poller/`, two substantive modules + entry point.

### 5.1 System Model

- **`segment.py` (pure).** No I/O. Functions:
  - `slug_for(remote, toplevel) -> str` — port the hook's
    `sed 's#/$##; s#.*/##; s#\.git$##'`, then basename-fallback when remote empty.
  - `esc(s) -> str` — `\`→`\\`, `"`→`\"`, tab→space (exact hook `esc()` semantics).
  - `segment_line(repo, slug, remote, sha, subject, author, files_changed, ts)
    -> str` — assemble the JSON line via the hook's literal template; field order
    `repo,slug,remote,sha,subject,author,files_changed,start_ts,end_ts`;
    `files_changed` a bare int; `start_ts == end_ts == ts`.
  - `parse_candidates(raw) -> list[Candidate]` — split the pass-1 `git log` output
    (one `"<full_sha> <short_sha> <cI>"` line per commit; all tokens whitespace-
    free) into `Candidate(full, short, cI)`; `day = cI[:10]`.
  - `shas_in_segment(lines, repo) -> set[str]` — parse existing day-file JSON lines,
    return the set of `sha` whose `repo` matches (dedup key is `(repo, sha)`).
- **`poller.py` (impure shell).** `discover_repos`, the git subprocess calls, the
  `flock` guard, atomic `O_APPEND` writer, and `poll(...)` orchestration.
- **`__main__.py`** — argparse + `main()`, entry point `panopticon-git`.

### 5.2 Interfaces & Contracts

Output line (one per commit), appended to `segments/git-<day>.jsonl`:

```
{"repo":"<toplevel>","slug":"<slug>","remote":"<remote.origin.url|>","sha":"<%h>","subject":"<%s>","author":"<%an>","files_changed":<int>,"start_ts":"<%cI>","end_ts":"<%cI>"}
```

- `<day>` = `%cI[:10]` (committer-local date, offset preserved).
- `start_ts == end_ts == %cI`. **Load-bearing** — the consumer windows + sorts on
  these.
- `slug` = remote-origin basename, trailing `/` and `.git` stripped; else
  `basename(toplevel)`. **Must match the hook** — it is the percept handle.
- `files_changed` = `git diff-tree --no-commit-id --name-only -r --root <sha> |
  count non-empty lines` — the hook's exact command (root commit's files count;
  default merges → 0).
- Escaping: backslash, double-quote, tab→space. JSON number for `files_changed`.

Per-commit field commands (mirror the hook, with `<sha>` substituted for `HEAD`):
- ts/short already obtained in pass-1; `git log -1 --pretty=format:%an%x00%s <sha>`
  for author + subject (NUL split once; subject single-line, taken as the tail);
  `git config --get remote.origin.url` once per repo; the `diff-tree` above for
  `files_changed`.

CLI: `panopticon-git [--dev-root ~/dev] [--state-dir DIR] [--since 7.days] [-v]`.

### 5.3 Data, State & Ownership

- Owns nothing persistent of its own. Reads repos under `--dev-root`; writes only
  `segments/git-<day>.jsonl` and a single lockfile under `state_dir()`.
- Dedup state = the `(repo, sha)` set already present in each target day-file,
  loaded once per file per run and cached.

### 5.4 Lifecycle, Operations & Dynamics

`git-poller.service` (oneshot, `ExecStart=panopticon-git`) + `git-poller.timer`
(`OnCalendar=*:0/5`, `Persistent=true`). Each fire:

1. Acquire a non-blocking `flock` on `state_dir()/git-poller.lock`; if held, a poll
   is already running — exit 0 (no overlap).
2. `discover_repos(dev_root)` → for each direct child of `dev_root`, run
   `git -C <child> rev-parse --show-toplevel` (handles `.git`-as-file worktrees);
   keep non-bare work trees (`--is-bare-repository` false). Non-repos skipped.
3. Per repo: read `remote.origin.url`, derive `slug`; **pass 1** —
   `git log --branches --since=<since> --pretty=format:%H %h %cI` enumerates
   candidates across all local heads (not just HEAD; not `--all`, which would pull
   in remote-tracking commits the hook never saw).
4. Per candidate: compute `day` + `seg_path`; load that file's `(repo, sha)` set
   (cached). If `(repo, short_sha)` present, skip. Else **pass 2** — fetch
   author+subject + `files_changed` via the hook's commands, format with
   `segment_line`, atomically append, and add to the cache.

### 5.5 Invariants, Assumptions & Edge Cases

- **Atomic append.** One `O_APPEND` write per line; line ≪ `PIPE_BUF` (4 KiB) —
  the multi-writer safety the hook and `RawStore` rely on.
- **Empty remote** → empty `remote`, slug from toplevel basename.
- **Merge commits** → `diff-tree` (no `-m`) emits no files → `files_changed: 0`,
  matching the hook. Octopus/exotic merges share this default-merge behaviour.
- **Subjects** (`%s`) are single-line; no embedded newline to escape.
- **Short-sha dedup** is keyed `(repo, sha)`, so a shared short prefix across two
  repos cannot false-skip. Residual: if a repo's abbreviation length grows between
  polls, a commit can be re-emitted once (rare, self-limiting); accepted.
- **Branch coverage.** `--branches` captures commits on any local head, including
  branches not currently checked out. **Residual gaps** (accepted, documented):
  commits on a detached HEAD never pointed at by a ref; commits older than the
  `--since` horizon when the host was down longer than the horizon. The objective
  is "commits within the rolling 7-day committer-date horizon," not "every commit
  ever."
- **`%cI` day-file stability.** The committer offset is stored in the commit, so
  later DST/timezone changes do **not** move a sha to a different day-file — dedup
  is stable. (A commit whose stored-offset date sits outside the consumer's local
  window is a consumer concern; byte parity preserves the hook's behaviour.)
- **Multi-worktree.** Two worktrees of one repo discovered as separate `~/dev`
  children share refs, so each would emit the same commits under its own `repo`
  path → duplicate rows with distinct `repo`. Uncommon for a flat `~/dev/*`;
  documented limitation, not engineered around.
- **Submodules / nested repos** under `~/dev/foo/...` are out of scope (discovery
  is `~/dev/*`, one level — Non-Goal).
- **Race.** `flock` removes poller-vs-poller overlap entirely. Hook-vs-poller can
  still double-write a sha within a small check-then-append window (the hook does
  a bare `>>` with no lock); accepted during transition, closed by ISSUE-006
  step 2. The consumer is expected to tolerate/dedup duplicate shas meanwhile.

## 6. Open Questions & Unknowns

Resolved via user decision (2026-06-05): discovery = glob `~/dev/*`; cadence =
systemd timer @ 5 min; horizon/backfill = 7 days (`--since=7.days`, stateless).
None blocking. `--since` and `--dev-root` are CLI-overridable.

## 7. Decisions, Rationale & Alternatives

- **Mirror the hook's commands vs. reconstruct fields from one `git log`.** Chosen:
  mirror. Reusing the hook's exact `git log -1 / diff-tree` invocations per commit
  gives byte parity by construction and sidesteps delimiter-safety hazards of a
  packed multi-field log line. Cost is bounded by dedup (only new commits pay).
- **`--branches` vs default HEAD vs `--all`.** Chosen: `--branches`. HEAD misses
  commits on other local branches the hook captured; `--all` over-captures
  remote-tracking commits the hook never saw. `--branches` = exactly the local
  history a push hook would have fired on (modulo never-reffed detached HEAD).
- **Stateless `(repo, sha)` dedup vs. persisted cursor/`seen.json`.** Chosen:
  stateless. The day-file already records every emitted sha across *both* writers,
  so it is the authoritative dedup set; a cursor is a second source of truth that
  drifts and cannot see hook-written shas.
- **Hand-rolled `esc` + template vs. `json.dumps`.** Chosen: hand-rolled. The
  contract is the hook's bytes, not "valid JSON"; `json.dumps` escapes tabs as
  `\t` instead of flattening to space and may differ on control chars/order.
- **Timer vs. long-running watcher.** Chosen: timer — env-agnostic, cheap,
  reboot-safe, no restart/signal machinery; matches the `segmentizer` sibling.

## 8. Risks & Mitigations

- **Contract drift from the hook.** Mitigation: a **differential** test runs the
  real hook and the poller against the same temp repo and asserts identical lines,
  across commit shapes (root, normal, merge, empty, mode-only, rename, no remote,
  trailing-slash remote, hook-preseeded dedup). Plus a captured golden line for
  escaping (quote/backslash/tab).
- **Double-write dup shas (hook-vs-poller).** Mitigation: `(repo, sha)` dedup;
  residual race accepted + documented; fully closed by ISSUE-006 step 2.
- **`files_changed` divergence.** Mitigated by using the hook's exact command;
  any residual (exotic merges) is informational, not used for windowing/keying.
- **Retention depends on `segmentize` running.** Documented; not the poller's job.

## 9. Quality Engineering & Validation

- **Pure unit tests** (`segment.py`): `slug_for` variants (trailing slash, `.git`,
  no remote → basename); `esc`/`segment_line` **golden byte-match** vs. the
  captured hook line; `parse_candidates`; `shas_in_segment` `(repo, sha)` keying
  incl. cross-repo prefix collision.
- **Differential integration test** (`poller.py`): build real temp git repos under
  a temp `--dev-root`; for a battery of commit shapes, run the **real hook** and
  the poller and assert byte-identical segment lines. Then assert: second `poll`
  is a no-op (dedup); a hook-preseeded sha is not re-emitted; a commit on a
  non-checked-out branch IS emitted; bare repo / non-repo child skipped; overlap
  blocked by `flock`.
- `just test` + `just lint` green (ruff, zero warnings).

## 10. Review Notes

Adversarial review (gpt-5.5 / codex, 2026-06-05): 3 blockers + several shoulds,
all folded above — `--branches` traversal (was HEAD), `(repo, sha)` dedup key (was
bare sha), hook-exact `files_changed` + per-commit field commands (was packed
`git log`), `flock` overlap guard, `git rev-parse` discovery (worktree/bare),
differential hook-vs-poller test, and reworded objective (7-day horizon, not
"every commit"). Not bugs: `%cI` day-file stability under DST. Accepted
limitations: multi-worktree dup rows, never-reffed detached HEAD, host-down >
horizon, submodules out of scope. Decisions locked.
