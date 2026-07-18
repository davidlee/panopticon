# Implementation Plan SL-003: Niri adapter

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Three phases behind the `CompositorSession` contract SL-002 defined, each ending
green and independently reviewable. The split follows the pure/imperative seam
and the design's module shape (`design.md §5.1`):

1. **PHASE-01 — protocol + pure projection.** The impure socket shell
   (`niri/protocol.py`) and the pure accumulator (`niri/projection.py`). This is
   the risk-bearing core: it is where the golden captures land as fixtures and
   where DL-6 (focus from the focused workspace's `active_window_id`) is proven.
2. **PHASE-02 — session + normalization + equivalence.** The stateful glue
   (`niri/session.py` + `NiriClient`) that turns the projection into a
   snapshot-first neutral observation stream, plus the cross-compositor
   equivalence test that pins "comparable" to a falsifiable assertion (F-6).
3. **PHASE-03 — live wire-up.** The two changes *outside* `compositor/niri/`
   that make data flow: `detect.py`'s D7 completion and `histogram.py`'s R4
   de-conflation. `--compositor auto` then runs Niri live end-to-end.

The design (`SL-003 design.md`) is canon; this plan does not re-litigate it. It
records only the sequencing and the implementation-surface facts confirmed by
re-grepping the current tree at plan time (below).

## Sequencing & Rationale

**Why this order.** PHASE-01 is foundational: the projection's shape and the
`active_window_id` focus model (DL-6) must be settled and fixture-locked before
the session can diff over it. PHASE-02 depends on a green projection to derive
observations and to stand up the equivalence test. PHASE-03 depends on
`NiriClient` existing (PHASE-02) before `detect.py` can wire it; the histogram
change rides along in the same phase because both are the "outside `niri/`" edits
the delivery boundary carved in (`slice-003.md` Non-Goals) and both are needed
for a live end-to-end `auto` run.

**Each phase ends green.** PHASE-01 and PHASE-02 are pure/near-pure and fully
in-jail testable against fixtures. PHASE-03's automated VTs (`detect`, `histogram`)
are in-jail; only the true end-to-end (`VH-1`) needs the host, and it is
non-gating — the SL-002 close showed the jail cannot run the live compositor.

**Behaviour-preservation.** PHASE-03 is the only phase touching shared code
(`detect.py`, `histogram.py`). EX-3 makes the SL-002 suites the proof: they stay
green unchanged. The neutral model / runner / events / schema and the Sway
adapter are never touched (a slice Non-Goal).

## Implementation-surface facts (re-grepped at plan time, 2026-07-18)

Confirmed against the current tree so the phases rest on real paths, not the
author-time design:

- **Code lives under `panopticon/`** — the design's `compositor/…` paths are
  package-relative. Real paths: `panopticon/compositor/{model,runner,events,
  detect}.py`, `panopticon/compositor/sway/{_i3ipc,project,session}.py`,
  `panopticon/segmentizer/{derive,histogram}.py`. New code lands at
  `panopticon/compositor/niri/{protocol,projection,session}.py`.
- **The contract is intact** — `model.py` carries `WindowRef`, `DesktopState`
  (`to_dict`), `DesktopObservation`, and the `CompositorSession` /
  `CompositorClient` Protocols (`producer`, `session()`); `events.py::encode(obs,
  producer)` is the sole source/producer injector; `runner.py::process_session`
  writes `store.write(encode(...))` + `store.write_current(obs.state.to_dict())`
  per observation (the F-4/R5 current-write mechanism). The Sway session
  (`sway/session.py`) already yields `snapshot` first then `window_focus` /
  `window_title` / `workspace_focus` — the exact neutral names Niri must match
  (INV-N3).
- **`detect.py` seam is as designed** — `select_client(compositor)` maps
  `auto|sway|niri`; `niri` and `auto`-without-Sway raise `NotImplementedError`
  (the SL-003 seam); `_sway_reachable()` is the `SWAYSOCK`-env stand-in (RV-001
  F-1) PHASE-03 retires; `_sway_client()` lazily imports `I3ipcSwayClient` — the
  lazy-import pattern `NiriClient` mirrors.
- **`histogram.py` R4 gap confirmed** — `aggregate(segments, *, day)` buckets
  `per_workspace_seconds` on the bare `workspace` (`ws = f["workspace"]`). The
  de-conflation must key on output.
- **`focus_segment` carries `output` only when the source stream provides it**
  (`derive.py::_segment` omits `output`/`producer` when `None`). Niri observations
  carry `output`; legacy Sway segments do not. **Therefore the R4 key is
  `f"{output}/{workspace}"` when `output` is present, else the bare `workspace`**
  — this de-conflates Niri without disturbing historical Sway aggregation
  (keeping the existing histogram tests byte-identical, tightening EX-2 beyond a
  blanket `"None/1"`).
- **No niri-ipc python dependency.** Sway depends on `i3ipc`, but Niri is a direct
  JSON socket (SPEC-001 D3) parsed with stdlib `json.loads`. The design's
  "pin niri-ipc `=26.4.0`" is **wire-format provenance** — the niri Rust release
  the goldens were captured from, recorded in each fixture header — not a package
  to add to `pyproject.toml`. PHASE-01 must not add a runtime dependency.

## Notes

- **Golden captures.** Three host captures exist (`design.md §9/§10`); capture 0
  (`niri-golden.ndjson`) is currently untracked in the repo root. PHASE-01
  relocates it (and re-captures 1/2 per the §9 snippet if the pasted text was
  lost) into `tests/fixtures/niri/`, version-stamped. They are the ASM-1 and DL-6
  evidence and cannot be regenerated in-jail.
- **DL-6 residual.** The floating-window-on-a-non-active-workspace edge is judged
  impossible (user-confirmed) and carried as PHASE-01 `VH-1` (non-gating), with the
  occupancy-test fallback (DL-6 alternative b) documented if it ever holds.
- **Non-gating host checks.** PHASE-01 `VH-1` (floating focus) and PHASE-03
  `VH-1` (live `--compositor auto`) both need the Niri host; neither gates phase
  completion, mirroring the SL-002 `nix run` VH treatment.
- **Highest implementation risk: the equivalence test (PHASE-02 VT-4).** It needs
  hand-built Sway and Niri fixtures that are *structurally aligned* (same logical
  focus-A→B-across-two-outputs scenario) so the F-6 assertion is a real equality,
  not a judgement call. Build the Niri fixture from the golden shapes and the Sway
  fixture from the existing `sway/project` test shapes; if alignment proves
  fragile, `/consult` before weakening the assertion.
- **Design reconciled at plan time.** R3 / the §5.4 histogram rule were changed
  from `"None/1"` to a bare-`workspace` fallback when `output` is absent, so legacy
  Sway aggregation stays byte-identical (PHASE-03 EX-2). No other design change.
