# Compositor-neutral core and Sway migration

## Context

Realises SPEC-001 (`references --role implements`). Today `panopticon.sway_watcher`
consumes Sway's i3ipc model directly and emits `source:"sway"`. This slice stands up
the compositor-neutral core — shared model, runner, event encoder, adapter contract,
CLI + detection — and moves Sway behind it as the first (and, for this slice, only)
adapter, emitting the migrated schema. Behaviour-preserving except the one documented
D5 focus-bug fix. No Niri yet (SL-003).

This is the load-bearing slice: get the neutral contract wrong and SL-003/SL-004
inherit a Sway-shaped core. Key spec findings it must honour: the snapshot model
inverts **pull→push** (H2 revised — the adapter yields its own initial snapshot;
`process_session` stops calling `get_tree`); the segment tier is **not** neutral
(H4 downgraded — hardcoded `source:"sway"`, the literal `sway_disconnected` event-name
contract, and the `(app_id, workspace)` key collision → D8).

## Scope & Objectives

Provisional phase breakdown (finalise at `/plan`; each phase ends green,
Sway fixtures preserved except the D5 change):

1. **Neutral core.** `compositor/model.py` (WindowRef/DesktopState/DesktopObservation,
   CompositorSession/Client protocols — `output` first-class per D4),
   `compositor/runner.py` (generic loop, snapshot acquisition inverted pull→push),
   `compositor/events.py` (neutral encoder emitting the **final** schema —
   `source:"desktop"`+`producer`+`window_id` — from the start, so downstream fixtures
   land once). Retire dead `ipc.py` reconnect (D6; deletes `test_sway_ipc` coverage
   of it). Behaviour-preserving via a thin Sway shim.
2. **Sway adapter + D5.** Relocate `state.py`/`events.py`/`_i3ipc.py` into
   `compositor/sway/` behind a tree-projection `CompositorSession`; derive
   workspace/output from the focused window on every focus event (D5 fix — its own
   before/after test isolating it from mechanical drift). Golden/equivalence tests.
3. **Schema migration + segmentizer.** `_SOURCES`/`_SEGMENT_PREFIX_FOR_RAW` gain a
   `desktop` entry; the hardcoded segment `source:"sway"` (derive.py:35) and the
   `sway_disconnected` close-contract (derive.py:82) neutralised; focus key → D8
   `(producer, output, app_id, workspace)`; `current/sway.json` side-write (D2, OQ-1);
   store filenames fall out (`raw/desktop-*.jsonl`, `current/desktop.json`).
4. **CLI + detection.** `panopticon-desktop` with `--compositor auto|sway|niri`
   (D7 — connect-validated auto-detection, both-set resolution); keep `panopticon-sway`
   wrapper; move `nix meta.mainProgram`. `desktop_watcher/__main__.py`.

## Non-Goals

- The Niri adapter — protocol, projection, normalization (SL-003).
- Dropping the `current/sway.json` compat / repointing SATAN (SL-004, OQ-1).
- Renaming systemd/HM units (SL-004, OQ-2 — ExecStart is `lib.getExe`, rename-safe).
- A universal Wayland abstraction (D4 — two-compositor model only).

## Summary

Neutral core + Sway-as-first-adapter, emitting the migrated `source:"desktop"` schema,
behaviour-preserving bar the D5 fix. The foundation SL-003/SL-004 build on.

## Follow-Ups

- OQ-4 (migration-day historical-data reaping) is exercised here if cutover lands in
  this slice; otherwise carried to SL-004. Keep `sway` `_SOURCES`/retention entries on
  a raw-retention-dated retirement.
</content>
