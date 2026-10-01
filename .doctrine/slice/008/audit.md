# Audit SL-008: digest privacy-surface flag for gate audit

Hand-authored (no `slice audit` scaffold yet). Conformance of the delivered
change against `design.md` (D1–D6, I1–I6) and the plan's criteria. Evidence
is counts only (I4).

- **Auditor:** claude (opus-5-5), 2026-10-02.
- **Gate at HEAD:** `just check` green — **798 passed, 3 skipped, ruff clean.**
- **Commits:** `da2b513` (PHASE-01), `5787f94` (PHASE-02), `e649908`
  (PHASE-03 evidence).

## Verdict

**PASS, with one accepted limitation** (reason accuracy, below).
`PrivateSurface` is the single source for schema, prompt, parser and type
(PHASE-01 EX-1). The audit reuses `gate`, `normalise_deny_entry`,
`normalise_path` and `StageStore`, with no parallel matching or layout logic
(PHASE-02 EX-1).

## Design conformance

| item | evidence |
|---|---|
| D1 in the digest schema, pre-backfill | `prompt.py` `DIGEST_SCHEMA`; prompt v4 live on 23 records before the backfill |
| D2 closed enum, `public` / `other_private` | `PrivateSurface`; `test_schema_enum_is_the_surface_vocabulary_and_comes_last` |
| D3 off-list / missing → `bad_shape` | `_digest`; `test_bad_shape` cases for missing, off-list, `None`, `Draft` |
| D4 audit as its own function | `__main__.audit` beside `run`; shared `_load_config`; pure core `audit.py` |
| D5 "still exposed" by the real gate | `audit._regate`; `test_a_record_the_current_gate_rejects_is_covered` (deny and allow) |
| D6 `host/<first segment>`, verified | `audit.candidate`; `test_candidate` (www, `;params`, query, `..`, bare-TLD guard) |
| R3 field last | `test_schema_enum_is_the_surface_vocabulary_and_comes_last` |
| I1 v4 records carry the field | `test_record_holds_the_private_surface_as_its_bare_value`; 23/23 live records |
| I2 no network in the audit | `audit.py` is in `PURE_MODULES` (`test_digest_purity`) |
| I3 audit writes nothing | `test_audit_lists_exposed_flags_and_candidates_and_writes_nothing` (snapshot) |
| I4 no private data committed | notes and audit hold counts only; tests use `*.example` hosts |
| I5 interactive only | README states it; no unit file runs `--audit` |
| I6 candidates parse and deny | `test_every_candidate_parses_as_config_and_denies_its_url`; TOML-ready via `json.dumps` |
| `_printable` (review finding 3) | `test_printable_escapes_controls_in_dry_run_titles`, `test_audit_escapes_terminal_controls_in_every_field` |

## Human verification (PHASE-03, see notes.md)

- **VH-1 PASS.** Original 3 pages through prompt v4: `public`, summaries
  comparable to v3.
- **VH-2 PASS on detection, partial on reason.** 4/4 synthetic private pages
  flagged non-public; 2/4 with the intended reason (inbox → `personal_record`,
  order history → `account`). Accepted: the audit acts on public versus
  non-public; the reason only labels the row. Revisit the meanings if real
  flags show the same confusion.
- **VH-3 PASS.** Canary of 20: 0 failures, 0 flags; all hosts public sites.

## Doctrine gates

- `slice verify-vt SL-008`: PHASE-02 VT-1, VT-2 PASS. PHASE-01 is not
  reported: its tracking sheet was hand-made after `slice phases` failed to
  create it (see Findings). Its VT-1/VT-2 tests exist and pass under `just
  check`.
- `slice conformance SL-008`: 6/6 design targets delivered, 0 undelivered.
  Undeclared: the digest test files (declared `scope-relevant` by glob) and
  doctrine records.

## Findings

- **F1 (process, repeated).** A directory-wide `ruff format` again rewrote
  ~25 unrelated files. Caught before commit and restored from HEAD; no net
  effect. `mem.fact.panopticon.ruff-format-not-enforced` already recorded
  this gotcha, but memories were not retrieved before work began.
- **F2 (doctrine bug).** `doctrine slice phases` reported "Phases up to date"
  while PHASE-01's sheet was missing; `verify-vt` then skips that phase.
  Belongs upstream in doctrine.
- **F3 (operations).** Deleting records and running `--limit N` re-digests
  the N newest pending pages, not the deleted ones (SL-007 D4: no re-digest
  machinery). The 3 original pages fall to the backfill.

## Carried forward

- Backfill on prompt v4, `--audit` after each chunk (operational; follows
  close).
- If triage lands and filters pages out of the digest, those pages lose the
  flag (slice follow-up).
