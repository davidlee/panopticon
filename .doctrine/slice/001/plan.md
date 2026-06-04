# Implementation Plan SL-001: host-side git commit poller

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.

## Overview

Three phases, mapped onto the pure/imperative split plus an ops tail:

1. **PHASE-01 — pure core (`segment.py`).** Everything testable without git or
   disk: slug derivation, the hook's `esc()`, JSON-line assembly, candidate-log
   parsing, `(repo, sha)` dedup extraction. This is where byte parity is pinned,
   against a golden line captured from the real hook.
2. **PHASE-02 — impure shell (`poller.py` + `__main__.py`).** The thin shell
   around the core: discovery, the two-pass git reads, `flock`, atomic append,
   `poll()`, and the CLI. Correctness is proven by a *differential* test that runs
   the real hook beside the poller on the same temp repos.
3. **PHASE-03 — ops wiring.** Entry point, systemd unit + timer, docs. No new
   logic — pure deployment surface.

## Sequencing & Rationale

- **Pure before impure.** The contract risk is entirely in the bytes, and the
  bytes are decided by pure functions. Pinning them first (golden + collision
  tests) means PHASE-02 only has to wire real git into already-correct formatting.
- **Differential test as the parity proof.** Rather than freezing one golden
  string, PHASE-02 runs the *actual* hook and the poller against the same commits
  and asserts equality. This is the strongest guard against silent drift and was
  the key ask from the adversarial review.
- **New-commit-only cost.** PHASE-02's expensive per-commit git commands run only
  after dedup, so the enumerate-then-fetch ordering is load-bearing for cost, not
  just clarity — encode it in `poll()`.
- **Ops last.** The entry point + timer are only meaningful once the poller is
  green end-to-end; deferring them keeps earlier phases free of deploy concerns.

## Notes

- Ride existing seams: `store.state_dir()` for the root; the `RawStore`
  `O_APPEND`/atomic-rename pattern for writes; the `segmentizer.{service,timer}`
  shape for the systemd units. No parallel implementation.
- Retention is inherited free from `segmentizer.retention` (generic 90-day
  segment sweep) — no `git` source wiring needed; note the dependency only.
- Out of scope (Non-Goals): hook retirement (`.emacs.d` ISSUE-006 step 2),
  mounting segments into the jail, multi-root/config discovery.
