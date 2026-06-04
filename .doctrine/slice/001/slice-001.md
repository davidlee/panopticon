# host-side git commit poller

## Context

The SATAN git-activity sensor undercounts commits. Its feed is produced by a
global git `post-commit` hook (`.emacs.d/satan/bin/satan-git-post-commit`) wired
via host `core.hooksPath`. A bwrap-jailed agent (`clanker`) carries none of the
hook's prerequisites — the hooks-path symlink isn't bind-mounted, the segments
tree isn't mounted writable, the overlaid `$HOME` has no `~/.gitconfig` — so
jailed-agent commits never produce a segment row. The perception layer then
reasons from a deaf sensor and reports the user "idle / reading" while large
volumes of code ship.

Evidence (2026-06-05): `~/dev/forgettable` last 50 commits were 30 `clanker` /
20 `David Lee`; the 06-04 segment file held 16 rows, **all** `David Lee`, zero
`clanker`. Not author-filtering — the hook never fired in the jail.

Fix placement is decided (per `.emacs.d` ISSUE-006): capture moves host-side
into **panopticon**, which owns `~/.local/state/behaviour/`. A host-side poller
is env-agnostic, so it catches jailed commits the hook misses. The sandbox stays
sealed — the segments tree is **not** mounted into the jail.

## Scope & Objectives

- A new panopticon producer, `panopticon-git`, that polls tracked git repos and
  appends one JSONL segment per commit to `segments/git-<day>.jsonl`.
- **Byte-compatible** output with the existing hook (`satan-git-post-commit`) —
  same field order, escaping, slug derivation, and `files_changed` semantics —
  so the SATAN evidence consumer (`.emacs.d/.../dl-satan-memory-evidence.el`)
  parses both writers identically.
- Repo discovery by globbing `~/dev/*` for working trees.
- Driven by a systemd oneshot **timer @ 5 min** (modelled on `segmentizer`),
  not a long-running watcher.
- Writes **directly** to `segments/` (the documented git freshness exception),
  bypassing the nightly `raw/ → segmentize` batch, so commits surface within a
  poll interval.
- **Stateless dedup**: each poll enumerates `git log --branches --since=7.days`
  per repo and skips any commit whose `(repo, short sha)` already appears in the
  target day-file. The segment files are themselves the dedup state — no
  `seen.json` to persist or corrupt. This subsumes the 7-day first-run backfill
  and tolerates the hook co-writing the same sha during the transition.
- Objective is the **rolling 7-day committer-date horizon** across local heads —
  not "every commit ever". Accepted gaps: never-reffed detached-HEAD commits and
  host-down-longer-than-horizon (see design §5.5).

## Non-Goals

- **Retiring the host `post-commit` hook.** That is the deferred `.emacs.d`
  delta (ISSUE-006 step 2), out of this repo's scope. Until it lands, both
  writers may emit the same sha — handled by the sha dedup above.
- **Mounting segments into the jail.** Explicitly rejected; the sandbox stays
  sealed.
- **Routing git through the `raw/ → segmentize` pipeline.** Git is the freshness
  exception by design.
- **Repo discovery beyond `~/dev/*`.** No config file / multi-root in v1.

## Summary

Host-side, env-agnostic git poller as a panopticon producer; byte-compatible
with the hook; stateless sha dedup; 5-min systemd timer; writes straight to
`segments/git-<day>.jsonl`.

## Follow-Ups

- `.emacs.d` ISSUE-006 step 2: retire/demote `satan-git-post-commit` to end the
  double-write, reconcile AGENTS.md + hook CAVEAT docs. Premature until this
  lands.
