# Implementation Plan SL-002: Compositor-neutral core and Sway migration

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Cite entities by padded id (SL-002, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Four phases, strictly ordered, each ending green (`just check`). They descend
`design.md` §5/§7 directly: build the neutral contract + shell first (PHASE-01),
then the real Sway adapter behind it (PHASE-02), then wire the desktop stream
through storage + segmentizer (PHASE-03), then the entrypoint + detection + nix
packaging (PHASE-04). The design is locked (design.md §10); the adversarial-review
findings are already folded, so the plan's job is sequencing, not re-deciding.

Reminder of the operating reality ([[mem.fact.panopticon.niri-live-sway-dead]]):
Sway is dormant, so none of these phases produce observable data on the host —
SL-002 is scaffolding whose payoff is SL-003 (Niri). That lowers the stakes of the
migration mechanics (no live stream to disrupt) but not the stakes of the contract
shape, which SL-003 inherits wholesale.

## Sequencing & Rationale

**Why PHASE-01 before PHASE-02 (the phase seam, F7).** The tempting shortcut —
"stand up the neutral core and wire Sway through a thin shim in one phase" — is a
fiction: any shim adapting today's `AsyncSession` (`get_tree()`+`events()`) to the
new `observations()` contract *is* the phase-2 adapter (it must carry the
snapshot-first inversion and the D5 live projection). So PHASE-01 proves the neutral
core against a **fake** `CompositorSession` — the encoder, the runner loop, the
model, the reconnect/backoff — with zero Sway code. This is the load-bearing
contract; getting it green against fakes first means PHASE-02 is a pure
adapter-implementation problem, not a contract-design problem.

**Why the schema is final from PHASE-01 (schema-once, review correction 1).** The
encoder emits `source:"desktop"` + `producer` + `window_id` from the first phase, so
the fixtures the later phases (and SL-003) assert against land once. We do *not*
ship an interim `source:"sway"` and migrate later — that would rewrite fixtures
twice. The cost is that PHASE-01's tests are already desktop-shaped; the benefit is
no fixture churn downstream.

**Why PHASE-02 owns the D5 fix, isolated.** D5 is a deliberate behaviour change
bundled inside a large mechanical move. It gets its own before/after test (VT-1)
carrying the pre-fix (buggy) expectation as a documented note, so the
"fixtures stay green" gate stays legible — any *other* behaviour diff in the move is
a red flag (R1). The mechanism is the live projection (DD6, complying with D5):
focus identity from the event payload (race-free), workspace/output from a
`get_tree`-refreshed location index. This is the one phase where the review's F2
resolution has real teeth — the plan must not regress to get_tree-per-focus.

**Why PHASE-03 is a consumer phase, not a producer phase.** By PHASE-03 the desktop
events already exist (encoder from PHASE-01, real Sway source from PHASE-02). This
phase makes storage and the segmentizer *consume* them: the `RawStore` compat
side-write (DD7), the `_SOURCES`/retention registry entries, the D8 focus key, and
the F6 dual-name segment close. The dual-name close is the subtle one — historical
`raw/sway-*.jsonl` still carry the legacy `sway_disconnected` name and stay inside
the 7-day retention window, so the deriver must close on *both* names or their
reprocessing silently stops splitting at disconnect. The histogram-key widening (D8
at the aggregation tier) is explicitly deferred to SL-003 (R4/SQ3): it is inert for
Sway's globally-unique workspaces and only becomes load-bearing with Niri's
per-output unnamed ones, and it changes SATAN's `per_workspace_seconds` shape, best
coordinated with the Niri work.

**Why PHASE-04 is last and thin.** The entrypoint, detection seam, and nix
packaging depend on everything above existing. Detection is built as a *seam*: the
sway path resolves by connect-attempt; the niri/both-set path raises with an SL-003
pointer — honest about the single-adapter reality (DD10). The `nix meta.mainProgram`
move is load-bearing for `nix run` (D7) and is verified by VA-1/VH-1 rather than a
unit test.

## Notes

- **Test-file map (new vs relocated).** New: `tests/test_compositor_{model,events,
  runner,detect}.py`, `tests/test_compositor_sway_{session,project}.py`,
  `tests/test_desktop_main.py`. Relocated/edited per design §9: `test_sway_events`,
  `test_sway_runner` (a rewrite — the fake becomes a `CompositorSession`),
  `test_sway_state`, `test_segmentizer_derive`, and the `Backoff` tests out of
  `test_sway_ipc` (the `stream`/`Ipc*` tests are deleted). The exact
  relocate-vs-supersede call for the old `test_sway_*` files is a `phase-plan`
  decision at PHASE-02.
- **F9 completeness (PHASE-02 `phase-plan`).** Pin the exact structural-event set
  that refreshes the projection index, and the deriver's `output` retention across
  events that don't carry it.
- **SQ1 checkpoint (PHASE-03).** Confirm the `current/sway.json` field rename
  (`con_id`→`window_id`) is safe against the four out-of-repo verbatim readers before
  flipping the payload — a no-regression check, per review-001 § OQ-1.
- **Behaviour-preservation gate.** Every phase ends green; the only sanctioned
  behaviour delta across the whole slice is PHASE-02's D5 fix. Deliberate
  rename-driven assertion edits are enumerated in design §9 and expected.
