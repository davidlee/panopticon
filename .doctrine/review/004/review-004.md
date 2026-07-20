# Review RV-004 — reconciliation of SL-004

Adversarial-review ledger (ADR-007). Structured findings live in the sister
ledger toml; this prose companion carries the reviewer's framing.

## Brief

Close-out audit of SL-004 (desktop watcher docs + operational migration) — all four
phases completed & committed, HEAD `49948f2`, `just check` green (327 passed, 3
skipped, zero lint). Reviewed surface: the **parent tree** (not a dispatched
candidate — SL-004 was driven solo, not via `/dispatch`).

Lines of attack:

1. **Mechanical conformance** — does `slice conformance` read clean against the
   recorded source-deltas? (Registry hygiene, scope creep, dropped work.)
2. **The load-bearing carve (DEC-001 / design §5.1)** — Sway kept first-class;
   only the sway *storage* bridge (side-write + `_SOURCES`/retention row) retired.
   No adapter / `--compositor sway` / `panopticon-sway` entrypoint touched.
3. **Cross-repo external evidence (design R6)** — PHASE-02 (SATAN/emacs repoint) and
   PHASE-04 (flakes ops) land out-of-repo with no in-repo delta; their VA/VH
   evidence is manual/external. Is it captured and honest?
4. **The stranding hazard (design §5.4 / D3)** — the retention optimistic fallback
   is structurally un-hardenable; is the accepted risk still consciously held?
5. **Human-gated acceptance** — README VH-1 legibility eyeball; the doctor-SOURCES
   design-scope gap (IMP-001).

## Synthesis

**Closure story.** SL-004 landed its locked scope in full: compositor-neutral docs
(PHASE-01), the SATAN/emacs reader repoint (PHASE-02), the in-repo sway storage-bridge
retirement (PHASE-03), and the flakes ops refresh (PHASE-04). The load-bearing carve
(DEC-001 / design §5.1) held — `git diff --name-only` confirms no adapter,
`--compositor sway`, `panopticon-sway` entrypoint, or `runner`/`detect` file was
touched; only the two sway *storage* surfaces (side-write, `_SOURCES`/retention row)
were dropped. VT-1/2/3 are green in-repo; the external phases' VA/VH evidence is
recorded in `notes.md` with real cross-repo commit refs (design R6 — no in-repo
conformance signal for external repos).

**Conformance.** Read dirty on entry (9 source/test selectors `undelivered`) purely
because PHASE-03's source-delta was never recorded — git proves those files *were*
touched at `49948f2`. Bootstrapped the missing delta in-audit (F-1) and removed one
over-broad, never-delivered selector, `tests/test_segmentizer_derive.py` (F-2). The
registry now reads **11 conformant / 0 undelivered / 2 undeclared** — the two
undeclared being the slice's own `notes.md` + `slice-004.toml` bookkeeping, expected
noise.

**Standing risks, consciously held.**
- The retention **optimistic-fallback** (`retention.py:106-110`) is the deliberately
  un-hardened structural stranding path (design §5.4 / D3). Migrating the sway-raw
  fixtures to `desktop` cost its incidental test coverage (F-4, tolerated). This is
  acceptable: *no code test can assert "won't strand"* given the shared `focus-DAY`
  prefix; safety is a **deploy precondition** (no in-window `raw/sway-*.jsonl` at
  cutover — owner-confirmed, structurally permanent since Sway now writes `desktop`
  raws), carried into `/close` as a runbook note.
- Version skew `pyproject.toml` 0.1.0 vs `flake.nix` 0.2.1 (F-7) is a plan-sanctioned
  deferral (plan.md: separate chore unless trivially co-landed in PHASE-03; it was
  not) → **CHR-003**.

**Cross-repo resolution (post-landing, owner-confirmed 2026-07-20).** The downstream
0-byte `segments/focus-<today>` symptom seen mid-PHASE-03 was *caused by* the pre-drop
`_SOURCES` still keying `sway` while the live raws were `desktop`; PHASE-03's registry
retirement (`desktop`+`firefox`) fixed focus derivation on the host (focus segments
now ~30KB, real intervals, niri producer + titles). The sibling **IMP-001** doctor gap
(F-5) — `sleipnir-doctor-panopticon` SOURCES sway-keyed — was remediated in the flakes
repo as its own `fix(SL-004)` commit `5ff2eda7` (desktop+firefox; sway key dropped),
correctly kept *outside* the panopticon carve because DEC-001 fences a functional
SOURCES change out of the comments-only scope. Doctor now all-OK on host; IMP-001
closed (resolution `fixed`). This is exactly the design-D2 "one agent holds both ends
of the hose" cross-repo landing model working as intended.

**Tradeoffs accepted:** the un-hardened stranding path (deploy-precondition safety
over an impossible code guard); external-evidence attestation in lieu of an in-repo
conformance signal for three sibling repos (design R6). No blockers; the carve is
intact; the ledger is clean.

## Reconciliation Brief

The audit resolved every finding in-audit or externally — **there is no pending
reconciled-truth write against design.md or governance/spec.** `design.md` proved
accurate throughout (the carve, the stranding hazard, the R6 external-evidence model
all matched reality); no prose is stale, no ADR/spec is contradicted, no REV is
warranted.

### Per-slice (direct edit) — already applied in-audit
- `slice-004.toml` selector registry: removed the over-broad `design-target`
  selector `tests/test_segmentizer_derive.py` (F-2 fix-now). Conformance-load-bearing;
  design §6 carries no selector prose to mirror. Reconcile confirms, does not re-write.

### Governance/spec (REV)
- **None.** No governance or spec finding was raised.

### Delegated / captured elsewhere (no reconcile surface)
- F-5 → flakes `5ff2eda7`; **IMP-001 closed** (external repo, R6 evidence).
- F-7 → **CHR-003** (plan-sanctioned deferral).
- F-1 → PHASE-03 source-delta bootstrapped in the runtime registry (gitignored).

**Handoff to `/reconcile`:** confirm the clean brief, then advance to `/close`. Carry
into close as runbook/owner notes (not code gates): (a) the EN-2 deploy precondition
re-check before the next `home-manager switch`; (b) `daemon-reload` before `restart`
after a HM switch ([[mem.fact.nix.hm-user-service-daemon-reload]]); (c) `rm` the inert
leftover host `current/sway.json`.
