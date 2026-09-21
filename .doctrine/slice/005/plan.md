# Implementation Plan SL-005: Umbriel adapter

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Three phases deliver umbriel as a third peer adapter behind the SL-002
`CompositorSession` contract, plus the live wire-up so `--compositor umbriel`
(and `auto`) run end-to-end. The shape mirrors SL-003 (niri): a pure/impure
split (protocol shell + pure projection), then the session glue and equivalence
proof, then detection + CLI. It is deliberately *lighter* than SL-003 — umbriel
emits a full snapshot per event, so the projection is a snapshot-**replace**, not
an accumulator; niri's novelty detection, `WindowClosed` id-drop, and burst-order
permutations do not exist here (design §4).

niri/`{protocol,projection,session}.py` is the structural template throughout;
the shared `compositor/diff.py::diff_state` (landed by ISS-001) is the emission
core both adapters call — SL-005 writes **no** parallel diff logic (design DL-7).

## Sequencing & Rationale

The order is dictated by dependency, not preference:

- **PHASE-01 before PHASE-02** — the DL-6 model widen (`window_id: int | str | None`)
  must land first because umbriel ids are opaque hex strings; the pure projection
  (`to_state`, `_locate`, `focus_coherent`, `_pid`) is the total function the session
  folds over, so it is built and proven pure against the fixtures before any impure
  glue wraps it. Protocol (the socket shell) sits in this phase too — it is the other
  leaf with no dependency on the session.
- **PHASE-02 before PHASE-03** — the session's two-mode machine (burst gate + live
  diff) is what `detect.py`/`auto` ultimately hands to `run_watcher`; equivalence and
  the capture-1 → `derive_segments` attribution proof belong here because they exercise
  the session end-to-end. Wire-up is meaningless until the session emits correctly.
- **PHASE-03 last** — detection + CLI + the `docs/schema.md` producer entry. The
  producer entry is deferred to this phase on purpose (RV-005.8): adding a producer the
  code does not yet emit would make the public contract claim a source that is not live.
  Only here does umbriel actually flow, so only here is the doc true.

**Why the DL-6 widen rides PHASE-01, not PHASE-03.** It is a prerequisite of the
projection (which constructs `WindowRef` from string ids), not a wire-up concern.
`diff._identity` is already typed for `int | str | None`, so the widen is a one-field
model change plus the `docs/schema.md` `window_id` note; the SL-002/SL-003 suites stay
green (a type-only widen) — verified as EX-1/VT-1.

## Behaviour-preservation & the two adjudicated exceptions

The behaviour-preservation gate holds across SL-005 with two scoped, deliberate
exceptions, both adjudicated in RV-005 (design §10) and already reconciled — they are
*not* silent breaks:

1. **ISS-001** promoted `diff_state` to the shared `compositor/diff.py` and corrected
   its precedence (window-identity wins). Landed as a prerequisite before this plan;
   three niri/equivalence tests were updated to the corrected names. SL-005 consumes
   the shared core unchanged.
2. **DL-6** widens the SL-002-owned `WindowRef.window_id` type. A type-only widen that
   leaves the SL-002/SL-003 suites green (PHASE-01, EX-1).

Outside `compositor/umbriel/`, the only touched files are `model.py` (DL-6),
`detect.py` (probe), `desktop_watcher/__main__.py` (CLI choice), and `docs/schema.md`.
`histogram.py`, the event names, and the sway adapter are untouched — umbriel segments
carry `output`, so they inherit SL-003's `(output, workspace)` de-conflation key for
free (DL-5, no histogram change).

## The coherence surface (the sharp edge)

The design's late revisions concentrate in one place the plan must execute exactly:
the live **coherence hold** (PHASE-02, EX-2 / VT-2). Two timeouts, both **fail-safe**:

- **burst-completion timeout** — a socket that sends one family then goes silent-but-open
  must not wait forever; it raises → `run_watcher` disconnect (RV-005.5a).
- **coherence_timeout** — a live new-workspace windows-before-workspaces sequence that
  never resolves must **not** emit a `workspace=None` observation (that mis-derives: a
  `window_focus(ws=None)` reads as defocus, and the follow-up cannot reopen a segment
  from `running=None`). It raises → **disconnect/reburst**, re-seeding a fresh coherent
  snapshot — the same recovery as the burst timeout. Burst/snapshot itself never holds
  (a full snapshot is as coherent as umbriel gets), so there is no reconnect loop.

The common cross-workspace move (a pre-existing target) is always coherent — no hold,
no timeout. The hold bites only a genuinely new workspace whose `windows` event leads
its `workspaces` event; `_locate` never fabricates a label from the opaque id suffix
(the suffix is an internal id, not the display index — capture-0 L2), taking only the
output from the reliable id prefix.

## Fixtures & the RV-005.3 gate

Two live host captures are banked (`capture-0` within-workspace + transient `active==0`;
`capture-1` cross-workspace windows-before-workspaces ordering). Edges the captures
cannot force on demand (partial burst, both timeouts, coherence hold, scratchpad
focus/active, geometry-no-emit) are hand-authored from the capture vocabulary + the
design's event→mutation table, as SL-003 did.

One edge is explicitly *capture-or-accept* (RV-005.3, EX-4 / VA-1): whether per-workspace
`focused` persists on the last tiled window while focus rests on a layer surface. PHASE-01
attempts a live capture; if inconclusive or skipped, the Tier-2 over-count is recorded as
an accepted limitation in `notes.md` + `docs/schema.md` — never left silent. No design
invariant depends on the outcome.

## Explicitly deferred (not in SL-005)

Surfaced by RV-005, flagged for david, tracked as backlog candidates — dispositions,
not fixes, and named as such:

- **RV-005.5b** — `run_watcher` emits `compositor_reconnected` + resets backoff before
  the session's lazy connect (a shared runner+niri concern). Out of scope.
- **Sway transient micro-segment** on a two-step cross-output switch (pre-existing,
  orthogonal to ISS-001).
- **niri `pid:-1` / niri burst-hang** — DL-9 and the burst-completion timeout likely
  apply to niri too; noted for its backlog, not touched here.

## Notes

- `--prune` on `slice phases` is destructive; not used here (fresh materialisation).
- Phase ids and criterion ids are immutable — edits append, never renumber (design §5,
  the storage rule). VH-1 (host acceptance) is non-gating by construction: umbriel is
  unreachable in-jail, so fixtures are the sole in-jail verification.
