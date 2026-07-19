# Review RV-003 — reconciliation of SL-003

Adversarial-review ledger (ADR-007). Structured findings live in the sister
ledger toml; this prose companion carries the reviewer's framing.

## Brief

Post-implementation reconciliation audit of SL-003 (Niri adapter + minimum live
wire-up). Reviewed surface: `main` at `e347961` (solo, un-dispatched — phase
commits are the evidence). Design canon: `design.md` (locked 2026-07-18); plan
criteria: `plan.toml` PHASE-01..03 EN/EX/VT; governance: SPEC-001 (implements),
ADR-007 (this ledger).

Lines of attack:

1. **Mechanical conformance** — `slice conformance` + `slice verify-vt`: does the
   recorded source-delta registry agree with what git touched, and is every VT
   criterion attributable to a slice-touched test? (This is where the bodies were
   buried — see F-1.)
2. **Behaviour vs design** — full suite (`just test`), the phase VT criteria, and
   the DL-decisions (DL-2 burst gate, DL-4 both-connect→niri, DL-6 overview-inert,
   D9/D10/D11 focus model) against the implemented `compositor/niri/*` +
   `detect.py` probe + `histogram.py` R4 de-conflation.
3. **Behaviour-preservation gate** — the SL-002 neutral core / Sway adapter stay
   byte-untouched outside `detect.py`/`histogram.py` (PHASE-03 EX-3).
4. **Standing deferrals** — the reconcile-time notes already flagged in `notes.md`
   (F-P02-1 VT-4 wording, F-P03-1 i3ipc private teardown, F-P03-3/VH-1 live host
   check): are they consciously dispositioned, not silently shipped?

Invariants held: INV-N1 projection totality, INV-N2 snapshot-first, INV-N3 event
names (not field sets), the pure/imperative split (no clock/rng/socket in the
projection fold), and the immutability of `PHASE-NN` / `EN-/EX-/VT-` ids.

## Synthesis

**Verdict: ships clean.** SL-003 delivers the Niri adapter and the minimum live
wire-up its delivery boundary demanded. All 326 tests pass (+3 host-only skips);
`ruff` clean; the SL-002 neutral core / Sway adapter are byte-untouched outside
the two consciously-widened seams (`detect.py` D7, `histogram.py` R4), so the
behaviour-preservation gate (PHASE-03 EX-3) holds. All three phases' EX/VT
criteria are satisfied and — after F-1's fix — attributable.

**The one real defect was in the evidence, not the code (F-1).** The runtime
source-delta registry (`boundaries.toml`) had drifted: PHASE-02 was recorded as a
zero-width range at a pre-phase test commit (`3d43c38`), and PHASE-03's range
*started* at PHASE-02's actual code commit (`07c7c7e`) — orphaning it from both
phases. The symptom was a lying conformance signal (`session.py` "undelivered"
though present and committed) and four UNATTRIBUTABLE PHASE-02 VTs despite a green
suite. Re-recording PHASE-02 to `--commit 07c7c7e` restored the truth:
`undelivered:0`, six conformant design-targets, PHASE-02 VT-1..4 PASS. Worth
carrying forward as a lesson — a green suite does **not** imply a truthful
conformance ledger; the two must be cross-checked at audit (mem candidate).

**Standing risks, consciously accepted:**

- **F-3 — i3ipc private-internals teardown.** The sway auto-probe must undo
  `connect()`'s socket/reader setup by hand because i3ipc exposes no public close.
  Guarded (getattr + one-shot loop teardown backstop) and memory-anchored
  (`mem.fact.panopticon.i3ipc-no-public-close`). Fragile-by-necessity; revisit if
  i3ipc grows a public close.
- **F-4 — VH-1 unrun in-jail.** The live `--compositor auto` end-to-end proof on
  the niri host cannot run inside the bubblewrap jail (niri unreachable). Everything
  runnable here — fake-socket probe, deferred-import/`--help` smoke, full suite —
  is green. Non-gating; to be exercised on the host post-close.

**Non-issues confirmed:** the 18 conformance-undeclared paths are all legitimate
non-code touches (tests, the CHR-002 backlog item, harvested memories, `notes.md`,
`slice-003.toml`) — design-target selectors are the code touch-set by construction,
not the test/doctrine surface. F-2 (VT-4 wording) is a future-reader clarification,
not a divergence: the equivalence test satisfies VT-4 as written via the two-step
scenario. F-5 (a stale one-line docstring) was fixed in-audit.

## Reconciliation Brief

No governance/spec (REV) surface and no per-slice `design.md` edits are required —
implementation matches canon. The audit's own corrections (F-1 registry re-record,
F-5 docstring) are already applied and green; they are recorded here for the
reconcile pass to confirm, not to re-do.

### Per-slice (direct edit)
- *(none)* — `design.md` and `slice-003.md` already describe the shipped
  behaviour. F-2's single-step-vs-two-step caveat lives durably in `notes.md`
  (F-P02-1); no prose edit needed.

### Governance/spec (REV)
- *(none)* — SL-003 implements SPEC-001 as designed; SPEC-001 carries no
  coverage rows to reconcile (consistent with SL-002 / RV-001).

### Already-applied audit corrections (confirm only)
- `boundaries.toml` PHASE-02 delta re-recorded to `07c7c7e` (F-1) — runtime
  state; conformance now `undelivered:0`, VT-1..4 attributable.
- `histogram.py` header docstring de-sway-ified (F-5) — suite green.

### Standing deferrals (no reconcile action; carried to close/notes)
- F-3 i3ipc private teardown — accepted, guarded, memory-anchored.
- F-4 VH-1 live host end-to-end — deferred to the niri host, non-gating.

## Reconciliation Outcome

**No-op reconcile — confirmed.** The reconciliation brief carried zero REV items
and zero per-slice `design.md`/`slice-003.md` direct-edit items: the shipped
implementation already matches canon (SPEC-001, `design.md`). Nothing was written
through either reconcile surface.

Every finding is terminal:
- **F-1** (major, `fix-now`) — `boundaries.toml` PHASE-02 delta re-recorded to
  `07c7c7e`; conformance `undelivered:0`, VT-1..4 attributable. Runtime state, not
  a governance/spec surface.
- **F-2** (minor, `aligned`) — no divergence; caveat durable in `notes.md` F-P02-1.
- **F-3** (minor, `tolerated`) — i3ipc private teardown, guarded + memory-anchored.
- **F-4** (minor, `tolerated`) — VH-1 live host check deferred, non-gating.
- **F-5** (nit, `fix-now`) — `histogram.py` header docstring corrected in-audit.

No unresolved blocker; the close-gate is clear. RV-003 handed to `/close`.
