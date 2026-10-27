# Notes SL-010: content handoff: host replies with the captured page's path

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## Harvest
<!-- single-copy: updated in place each harvest; ids only, never restated content -->
fresh-as-of: <yyyy-mm-dd> · <PHASE-NN | stage> · <head-commit>

### Produced

### Learned

### Open

## Review passes

| pass | who / profile | cost | outcome |
|---|---|---|---|
| design review | pi `review` (deepseek-flash, max) | $0.024 | 12 findings, all held on probe; design revised (35a9d12) |
| PHASE-01 tests | pi `implement` | $0.037 | 29 red tests, sound; flagged VT-5 wording vs design |
| PHASE-01 impl | pi `implement` | $0.023 | green first pass; orchestrator read full diff, no changes |
| PHASE-02 ext | pi `implement` | $0.027 | static tests red→green, impl first pass; VA-1 by orchestrator, no changes |

What pi got wrong / gaps:
- Test writer did not guard against `trigger` leaking onto non-content events
  (would have reached the raw JSONL tier); orchestrator added the test.
- Global quotient forms carried no python/uv → workers could not run tests
  until the project forms landed (9fedb7a; `just quotient-forms`, `quotient allow`).

PHASE-03 docs written by the orchestrator (cheaper than a brief).

## VH-1 (user, 2026-10-27)

- Manual extract → path on the clipboard
  (`content/77/77ff9fb2….md`, exists). Pass.
- "No reply" observed first, against a stale 0.2.1 host process Firefox had
  kept alive across the profile upgrade — the timeout notification works.
- Same-page repeat → same path; dwell → no notification. Pass (user).

## Durable

- Duplicate-page replies depend on `ContentStore.store()` writing files
  before its dedup check (commented at the call site). Reordering `store()`
  breaks the duplicate reply silently.
- Firefox keeps the native host alive across a binary upgrade; a new host
  takes effect only after the old process exits (README § Notes).
- `doctrine slice phases` (0.47.0) skipped PHASE-01 while reporting "up to
  date"; its tracking sheet was hand-made.
