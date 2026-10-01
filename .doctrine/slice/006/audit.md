# Audit SL-006: panopticon-digest

Hand-authored (no `slice audit` scaffold yet — known CLI gap). Verification of
the completed implementation against `design.md` (decisions D1–D16,
invariants I1–I5) and the plan's EX/VT/VA/VH criteria. Method: an independent
fresh-context review of the slice diff (`git diff a7b8510..HEAD`) with
execution probes over the pure functions and an unconnected client (no
egress), plus the doctrine CLI gates below. Its findings were fixed in an
appended PHASE-05 and re-gated.

- **Auditor:** claude (opus-5-5), 2026-10-02.
- **Gate at HEAD:** `just check` green — **726 passed, 3 skipped, ruff clean.**
- **Phase deltas:** PHASE-01 `a7b8510..7447d8c`, PHASE-02 `7447d8c..d28efab`,
  PHASE-03 `d28efab..a6feec9`, PHASE-04 `a6feec9..32e567f`,
  PHASE-05 `2842307`.

## Verdict

**PASS — ready to close.** The privacy core holds: only host, title and
truncated `text_content` leave the machine (I1), only `digest/client.py`
imports a network module (I2), and dry-run touches neither network nor disk
(I3). No blocker or major finding. The review's five minors and the
actionable nits are fixed with tests that failed first; four were design-text
drift, now amended. VH-1 passed on the real store.

## Design conformance (D1–D16, I1–I5)

All conformant. Evidence per item is in the review; the notable ones:

| item | evidence |
|---|---|
| D4 deny always, allow narrows | rule order in `gate.py` `gate()`; `DEFAULT_DENY \| user deny` in `config.py` |
| D5 latest SHA per URL, no fallback | `select.py` `pending()` |
| D6 fsutil extraction | no other `os.replace`/`flock` in `panopticon/`; shared suites unedited |
| D10 trafilatura removed | absent from `pyproject.toml`, `flake.nix`, `uv.lock` |
| D11 host, not URL | `prompt.Page(host, title, text)`; host from `Pass` |
| D13/D14 failure split, hold-and-flush | `__main__.py` `_Ledger`; every abort returns before `finish()` |
| D16 path deny | `gate.py` `_normalise_path`, `_denied` |
| I1 | `prompt.build_request`; test asserts a path secret is absent from the body |
| I5 | held after m1 (below); caplog test covers a failing and a succeeding run |

## Findings and dispositions

Ids are the review's (m = minor, n = nit).

| id | finding | disposition |
|---|---|---|
| m1 | A key containing `\r`/`\n` made `http.client` raise `Invalid header value`, printing the key in the traceback (I5 leak). | **Fixed.** `run` refuses a key with surrounding whitespace or control characters (exit 2, names the env var only). |
| m2 | `pending` not total: a non-object index line, or a non-string title, raised and killed every run, dry-run included. | **Fixed.** Both are `bad_row`. |
| m3 | Design claimed the breakers bound a run "well under 2 h"; interleaved successes allow ~230 min. | **Design amended.** `TimeoutStartSec` is a backstop; killing a run is safe. Unit comment corrected. |
| m4 | Unit ran at WARNING, so the design's INFO log rows never reached the journal. | **Fixed.** `ExecStart=panopticon-digest -v`; a test pins it. |
| m5 | Design said "consecutive"; code counts each class since the last success (deliberate, PHASE-03 notes). | **Design amended** to match the code. |
| n1 | A NaN `quality_score` passed the gate (fail-open). | **Fixed.** Non-finite quality is `bad_row`. |
| n2 | `Retry-After: nan` crashed `time.sleep`. | **Fixed.** Non-finite falls back to backoff. |
| n3 | Deny paths dodged by `/a/../messaging`, `messaging;x`; `127.1`/`0x7f.1` not seen as IP literals; `twitter.com` missing beside `x.com`. Unreachable for Firefox-serialised URLs. | **Fixed.** Dot segments resolved, `;params` dropped, numeric final labels are IP literals (`local_host`), twitter.com private paths in `DEFAULT_DENY`. |
| n4 | Index `content_hash` used unvalidated in store paths (`../../x` escapes). | **Fixed.** Non-hex hash is `bad_row` before any path is built. |
| n5 | Dry-run logs, rather than prints, a pass whose content record is missing. | **Design amended** (accepted behaviour). |
| n6 | `digested_at` taken before the request; a `URLError` with a string reason logs kind `str`. | **Accepted**, cosmetic. |
| n7 | Up to 4 trailing content failures are marked at run end after a success. | **Design amended** as accepted residue. |
| — | `store.py` borrows `shard_path` from `ingest.content` (coupling). | **Deferred** to IMP-003. |

Findings from VH-1 (PHASE-04), recorded in `notes.md`:
- A LinkedIn compose page passed the gate and was sent. **Fixed**:
  compose/editor paths in `DEFAULT_DENY`.
- Entity `type` is free text and drifts. **Deferred** to IMP-002.
- The idea of a model-flagged audit of the gate is captured as IDE-004.

## Objective gates (doctrine tooling)

Phase deltas were recorded with `record-delta --start/--end`, since the phases
were executed solo, without delta binding.

- **`slice verify-vt SL-006` — all 20 VT criteria PASS.** PHASE-02 VT-4
  failed at first on keyword case only: the test asserts `Reason.SUPERSEDED`,
  but the mandate named `superseded`. The behaviour was always tested; the
  mandate keyword was corrected (the criterion id is unchanged).
- **`slice conformance SL-006` — 28 design-target paths conformant, 0
  undelivered.** Selectors were authored at close from the design's change
  surface. **Undeclared:** `panopticon/cli.py` plus three entrypoints
  (`desktop_watcher`, `firefox_host`, `git_poller` `__main__.py`), from the
  `configure_logging` consolidation (`2549f12`). It is a DRY refactor that the
  digest needed, recorded in `notes.md` but not in the design. **Accepted.**
  The other undeclared paths are tests and doctrine records, as expected.
- **`slice selector doctor`** — one advisory: `panopticon/amo.py` is
  unmatched because D15 deleted it. It is kept so the deletion counts as
  declared.

## Exit criteria

- **PHASE-01** EX-1..6: met. No second atomic-write or flock remains;
  extractor and trafilatura are gone; `tools.amo` imports; the I2 tripwire
  has no exemption list.
- **PHASE-02** EX-1..3: met. The purity tripwire covers the four core
  modules; every reason, config rejection and failure kind is tested.
- **PHASE-03** EX-1..4: met (`nix build` verified at phase end, per the
  progress note).
- **PHASE-04** EX-1..3: met. Docs no longer claim panopticon makes no network
  calls at all; OQ-2..5 outcomes are in `notes.md` as aggregates.
  VA-1 and VA-2 met.
- **PHASE-05** EX-1..3: met. Each code finding has a test that failed first.

## Behaviour-preservation gate

**Holds.** The content, store, segmentizer and git-poller suites have only
additions. `test_amo.py` changed one import line, for D15's move.

## VH-1 — live acceptance (PASS, 2026-10-02)

`openai/gpt-4.1-mini` with `--limit 3` against the real store: exit 0, 3
records, no failure markers, no provider failures. The model honoured strict
`json_schema` under `require_parameters` and `allow_fallbacks: false`. The
user accepted the records as the baseline.

## Carried forward

- IMP-002: closed entity-type vocabulary (decide with stage-2 triage).
- IMP-003: move `shard_path` to `fsutil`.
- IDE-004: model-flagged private surfaces to audit the deterministic gate.
- Operational, not slice work: set the user's own `deny` before the backfill;
  then enable `digest.timer`.
