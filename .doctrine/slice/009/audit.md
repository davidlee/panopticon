# Audit SL-009: digest: scheduled run through the LLM gateway

Hand-authored (no `slice audit` scaffold yet). Conformance of the delivered
change against `design.md` (D1–D7, §9) and the plan's criteria. Evidence is
counts only.

- **Auditor:** claude (opus-5-5), 2026-10-22, with an independent read-only
  pi review (`scripts/pi-review.sh`, deepseek) of the PHASE-01/02 diff.
- **Gate at HEAD:** `just check` green — **848 passed, 3 skipped, ruff clean.**
- **Commits:** `79e5f40` (PHASE-01), `5c93343` (PHASE-02), `9da7f9b`
  (PHASE-03 evidence), `ebf7912` (audit fixes). `~/flakes` edits (gateway
  model entry, digest service + timer) are the user's commits there.

## Verdict

**PASS** after the audit fixes. The review found no http endpoint the
validator accepts that reaches a non-loopback target. It found one real key
leak path (finding 1) and one wrong privacy statement (finding 2); both are
fixed. One limitation accepted (finding 7).

## Design conformance

| item | evidence |
|---|---|
| D1 loopback http, IP literal only | `config._is_endpoint_url`, `_is_loopback_ip`; `test_accepts_http_to_a_loopback_ip`, `test_rejects_http_to_a_non_loopback_host` (localhost, 0.0.0.0, zone id, numeric/trailing-dot spellings) |
| D1 userinfo, port | `test_rejects_userinfo_in_the_endpoint`, `test_rejects_a_bad_port` |
| D2 key from a file | `KeyFile`, `__main__._read_key_file`; key-file suite in `test_digest_main.py` |
| §5.2 at most one key source; default env | `config._key_source`; `test_rejects_both_key_sources_without_echoing_a_value`, defaults tests |
| §5.2 key read after `--dry-run` / `enabled` | `test_disabled_with_a_missing_key_file_is_exit_0` |
| §5.2 errors log path + class only | non-UTF-8 and NUL-path tests assert neither bytes nor key in logs |
| §4 config stays pure | `config.py` in `PURE_MODULES`; `test_digest_purity` green |
| D3 routing pin unchanged | `prompt.py` untouched; VH-0 succeeded with the pin through the gateway |
| D4 403 per-page | `client.py` untouched |
| D5 units in `~/flakes`; reference units comments only | `systemd/digest.service` comment; timer unchanged |
| D6, D7 privacy facts | `docs/privacy.md` gateway paragraph |
| §5.3 records name the gateway | VH-0: a new record carries the gateway endpoint and model |

## Human verification (PHASE-03, see notes.md)

- **VH-0 PASS.** 3 digested, 0 failures; strict `response_format` survives LiteLLM.
- **VH-1 PASS.** Service run: success, 50 digested (the per-run cap), 0 failures; timer listed.
- **VH-2 PASS.** `--audit` exit 0, same output shape.

## Doctrine gates

- `slice verify-vt SL-009`: PHASE-01 VT-1 PASS. VT-2 reports FAIL on a
  keyword match only: the plan lists `KeyFile`, and the tests drive the key
  file through config (`api_key_file`) without naming the class. The
  behaviour VT-2 expects is tested (key-file suite, 15+ cases).
- `slice conformance SL-009`: uninformative. The design declares no target
  selectors, so nothing can be conformant or undelivered. PHASE-01's
  recorded range starts at its `in_progress` stamp (`84e49e4`) and so
  includes unrelated commits (pi tooling, jail fixes, flake). PHASE-03's
  delta was recorded by hand (`--commit 9da7f9b`, notes only): its real
  changes live in `~/flakes` and the user's config.

## Findings

Review findings, adjudicated. Fixed in `ebf7912` unless marked otherwise.

1. **Fixed (medium).** A printable non-ASCII key passed the check, then
   `http.client` raised an uncaught `UnicodeEncodeError` whose args held the
   whole `Bearer …` header; a Latin-1 key was silently re-encoded. The key
   must now be visible ASCII (`[!-~]+`), env and file alike.
2. **Fixed (medium).** `privacy.md` said the gateway keeps page text on the
   machine. Only the gateway's local copy does; the prompt still goes upstream.
3. **Fixed (low).** An inner plain space passed (VT-2 says inner whitespace
   fails). Covered by 1.
4. **Fixed (low).** A NUL in `api_key_file` passed config and crashed the
   run (exit 1). Rejected by `_is_key_path` and caught in `_read_key_file`.
5. **Fixed (low).** A directory key file leaked one fd. Now `os.read` with
   `os.close` in `finally`.
6. **Fixed (low).** `urlsplit` strips `\t\r\n` and leading controls, so such
   endpoints passed and failed every request as transport failures. The
   endpoint must be printable ASCII without spaces.
7. **Accepted (low).** An https host with an overlong DNS label still passes
   config and fails at send with an uncaught `UnicodeEncodeError` (exit 1).
   Predates SL-009; no key or page text is exposed. Non-ASCII hosts are now
   refused by 6.
8. **Fixed (low).** Opening a tty path could acquire a controlling terminal:
   `O_NOCTTY` added.
9. **Fixed (low).** README now gives the gateway model form.
10. **Fixed (low).** README separates the reference unit's env file from a
    Home Manager unit, which must supply the variable itself.
11. **Fixed (low).** Docstring design refs and log-scope wording.
12. **Fixed (low).** Test gaps: `~/` expansion, numeric/trailing-dot http
    refusals, IPv4-mapped with port, a weak leak assertion.

Earlier, in PHASE-01 review: the design's claim that `fstat` stops a FIFO
blocking was false (`open()` blocks first); fixed with `O_NONBLOCK`
(`79e5f40`).

## Open

- Backlog of gate-passing pages (~120 after VH-1) clears through daily runs.
- `~/flakes` `features/attention/behaviour.nix` header calls the panopticon
  input `path:`; it is `github:`.
- Nothing alerts on a failed scheduled run (design R2); the journal only.
