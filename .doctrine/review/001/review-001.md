# Review RV-001 — reconciliation of SL-002

Adversarial-review ledger (ADR-007). Structured findings live in the sister
ledger toml; this prose companion carries the reviewer's framing.

## Brief

<!-- Pre-reading + lines of attack: what this review is probing, the invariants
     it must hold the subject to, and where the bodies are likely buried. Seeded
     at `review new`; the reviewer fills it before raising findings. -->

## Reconciliation Outcome

No-op reconcile. Both findings are terminal and neither carries a write:

- **F-1** (minor) — `tolerated — carried to SL-003`. The `SWAYSOCK` env-probe
  vs connect-attempt gap is an intentional, in-code-documented seam
  (`detect.py:44-50`); the connect-validated D7 probe is scoped to SL-003.
  Already durable in `audit.md` (Drift vs design; SL-003 inheritances) and
  design DD10. No per-slice edit, no REV.
- **F-2** (nit) — `verified-by-inspection — host confirmation outstanding`. The
  `mainProgram` move + console-script + `--help` execution confirm the
  entrypoint; only the literal `nix run` invocation is unrunnable in-jail. A
  one-line host checkpoint, non-gating. No artefact write.

No reconciliation brief was authored (no per-slice direct edits, no
governance/spec REV items). Reconcile pass complete — handoff to /close.
