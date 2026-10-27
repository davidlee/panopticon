# Audit SL-010: content handoff: host replies with the captured page's path

Audited 2026-10-27 against `design.md` (locked 35a9d12) and `plan.toml`, at
27a6bc8 plus the audit's own fixes. Auditor: orchestrator (Claude), solo.

## Method

- Read the full code delta `2ec7053..HEAD` for the host, extension and docs.
- `doctrine slice verify-vt SL-010`, `doctrine slice conformance SL-010`.
- `just check`: 937 passed, 3 skipped; ruff clean.
- VH-1 result taken from `notes.md` (user, 2026-10-27).

## Evidence

| criterion | evidence | verdict |
|---|---|---|
| PHASE-01 VT-1..VT-5 | `verify-vt` PASS (after F1 fix); tests in `tests/test_firefox_host_main.py` reply-stream section, `tests/test_firefox_validate.py` | pass |
| PHASE-01 EX-1 behaviour preservation | delta removes no line from existing tests (only an import widened) | pass |
| PHASE-01 EX-2 `store()` unchanged | `panopticon/ingest/content.py` not in the delta | pass |
| PHASE-02 VT-1 static parity | `verify-vt` PASS | pass |
| PHASE-02 VA-1 | re-read below (Design vs built) | pass |
| PHASE-02 EX-1 dwell still stores, records URL | `extract(tabId, "dwell")` → `recordExtractedUrl` before send | pass |
| PHASE-02 EX-2 no path/title in notifications | every `notify()` call site is a literal, `NO_REPLY`, or `Capture failed: ${reason}` (closed set) | pass |
| PHASE-03 VA-1 docs | README § Manual capture and `docs/privacy.md` § Firefox match the shipped envelope, permissions, timeout | pass |
| PHASE-03 VH-1 | `notes.md` § VH-1 | pass |
| EX-* `just check` | green | pass |

Conformance, with the design §8 list declared as design-target selectors:
9 conformant, 0 undelivered, 7 undeclared. The undeclared paths are the
slice's own `.doctrine/slice/010/*`, the 0.3.0 version bump in `flake.nix`
(a09802e, the release), and `.gitignore`/`Justfile`/`flake.*` from 9fedb7a
(quotient forms, not SL-010) falling inside the PHASE-01 delta range.

## Design vs built

- D2/D4: `Stored.md_path = shard_path(ct_root, content_hash(text), ".md")`;
  `store()` hashes the same `text_content` under the same root, so the path
  is the one `store()` wrote. Duplicate → `Stored` (VT-1).
- D3: trigger is a closure parameter of `extract()`; one send site.
- D6: `_normalise_request` never raises; malformed manual → dwell, no id;
  only content events are touched (test guards the raw-tier leak).
- D7: reply keyed by `type`; unknown types ignored in `onHostMessage`.
- D9: the whole `ContentStore(...).store(...)` call is guarded; dwell
  benefits too.
- D10: `pending` entry is registered before `send()`; reply, timeout,
  disconnect and send failure each go through `cancelPending`, which
  returns true at most once per id, and only a true result notifies.
  Pre-send failures (injection, redaction) notify directly and register
  nothing. Every manual path ends in exactly one notification.
- R2: the host writes stdout only via `_write_reply` → `protocol.write_message`.

## Findings

**F1 — PHASE-01 missing its `[[phase]]` header (fixed in audit).**
`plan.toml` line 21 was a truncated comment (`# One [[phase]]`); the real
header was gone, so PHASE-01's keys parsed as top-level keys and were
ignored. Effects: `slice phases` skipped PHASE-01 (sheet hand-made) and
`verify-vt` judged PHASE-02 only. The header is restored; ids unchanged;
`verify-vt` now judges all six VT criteria. `notes.md` blamed a doctrine bug;
corrected. The doctrine-side gap is the known one (no plan validation:
unknown top-level keys pass silently).

**F2 — misleading manual notification on an empty frame result (low,
accepted).** If `executeScript({func})` resolves with no result,
`extract()` substitutes `{error: "extraction_returned_nothing"}` with no
`url`; `redact(undefined)` returns null, so a manual click reports
"unsupported page" instead of a read failure. Still exactly one
notification, and nothing is lost: dwell drops it silently, as before
SL-010, when no message arrived. Not fixed.

**F3 — wording: "fixed text only" (info).** Failure notifications include
`reason`, a closed host-side set (`extraction_error | empty_content |
store_failed`), as design §5.2 allows. No page data reaches a notification.
No action.

## Known gaps (accepted by design)

- D8: extension behaviour has static tests and VH only; no JS harness.
- R3: `pending` is in memory; a suspended event page drops the reply.
  Recovery: `just content-path`.
- The duplicate reply relies on `store()` writing files before its dedup
  check (commented at the call site; `notes.md` § Durable).

## Out of scope — follow-up candidates

- Reconnect backoff resets as soon as `connectNative` returns (design §2);
  a host dying at start respawns every second. No backlog item yet.
- Version drift: `pyproject.toml`/`__init__` 0.1.0 vs flake 0.3.0 —
  CHR-003 (its text cites 0.2.1).
- "Never captures page bodies" drift — ISS-002.

## Verdict

Built matches the design. One plan-file defect fixed in audit (F1); no code
change needed. Ready for reconcile.
