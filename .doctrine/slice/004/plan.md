# Implementation Plan SL-004: Desktop watcher docs and operational migration

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Four phases realise the locked design (`design.md`, 2026-07-20): a cross-repo
close-out that refreshes docs, repoints SATAN, retires the sway storage-naming
bridge, and refreshes the HM unit ops — while keeping Sway a first-class
compositor (DEC-001). Three phases touch external repos or docs; only PHASE-03 is
an in-repo code change, so it is the sole carrier of automated `VT` verification.

## Sequencing & Rationale

**The one hard constraint is repoint-before-drop** (design §5.4). Everything else
is free ordering. The chosen sequence:

- **PHASE-01 (Docs) first** — the largest surface, zero runtime coupling. Read the
  live event names/fields from code (not the stale doc) so schema.md reconciles to
  `derive.py`, not to itself. It legitimately *leads* the code: schema.md describes
  the post-slice reality (sway retired) before PHASE-03 lands the retirement — an
  intra-slice window that closes when the slice lands as a unit.
- **PHASE-02 (SATAN repoint)** — the gating external phase. Safe as a zero-downtime
  move because the side-write already writes `current/desktop.json` as primary
  (design §5.3, content-identical), so the readers switch to a file that already
  exists and is fresh. Must complete before PHASE-03.
- **PHASE-03 (In-repo retirement) LAST among the coupled pair** — drops the
  side-write + the `('sway','focus')` registrations only once the readers no longer
  depend on `current/sway.json`. The behaviour-preservation gate (VT-4) proves the
  Sway adapter and `--compositor sway` survive untouched.
- **PHASE-04 (flakes ops)** — orthogonal cosmetic refresh, ordered last so it never
  blocks the retirement. Unit name kept (D4), so no systemd churn.

**Why external phases carry no VT.** PHASE-02 and PHASE-04 edit satan / .emacs.d /
flakes — repos outside doctrine's phase-delta and conformance ledger (design R6).
They cannot produce an in-repo source-delta, so their evidence is `VA` (agent grep
of the external tree) + `VH` (host behaviour) + the commit refs harvested into
`notes.md` at close. This is deliberate and honest, not a coverage gap: the plan
must not expect an in-repo delta from a purely-external phase.

**Deploy ordering (host, human — not enforceable in-repo).** Rebuild SATAN/emacs
before the retired watcher: while both `current/*.json` files still exist the
readers are safe on either; reversing it strands old SATAN without `sway.json`.
Captured as a runbook step at execution / in `notes.md`.

## Notes

- **OQ-4 / stranding is structural** (design D3/R4): with `desktop` and `sway` raws
  sharing the `focus-DAY.jsonl` prefix, dropping the `sway` `_SOURCES` entry lets the
  reaper's optimistic fallback reap an un-derived in-window sway raw. No code test can
  assert "won't strand"; safety is the deploy precondition (PHASE-03 EN-2), and VT-3
  pins the retirement so it is not silently reverted. Chosen approach A (rely on
  precondition, don't harden the reaper) — the case cannot recur (Sway now writes
  `desktop` raws).
- **`sway_disconnected` close-branch** (`derive.py:99`) — a genuine micro-toss-up left
  to PHASE-03 execution (design F-5): lean keep (harmless, documents the historical
  dual-close); removing it perturbs the F6 test for zero live gain. Not a plan gate.
- **Incidental drift** (version skew `pyproject.toml` 0.1.0 vs `flake.nix` 0.2.1;
  README stale test count) — the test count is folded into PHASE-01 EX-1; the version
  skew is out of this slice's intent and left for a separate chore unless trivially
  co-landed while editing `pyproject.toml` in PHASE-03.
- **Write-access mechanism** (design OQ-3) — temporary `rw` binds vs un-jailed run,
  settled at execution; phase EN rows (PHASE-02 EN-1, PHASE-04 EN-1) gate on it.
  Path-portable references keep both mechanisms valid.
