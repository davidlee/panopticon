# Audit SL-007: digest closed entity-type vocabulary

Hand-authored (no `slice audit` scaffold yet). Conformance of the delivered
change against `design.md` (D1–D5) and the plan's criteria.

- **Auditor:** claude (opus-5-5), 2026-10-02.
- **Gate at HEAD:** `just check` green — **742 passed, 3 skipped, ruff clean.**
- **Commits:** `493bed4` (PHASE-01), `a717d23` + `27833e9` (PHASE-02),
  `1121e6c` (revert of unrelated formatting, see below).

## Verdict

**PASS.** One `EntityType` is the single source of truth for the schema
enum, `Entity.type` and the parser (EX-1). VH-1 passed for both prompt
versions on the real store.

## Design conformance

| item | evidence |
|---|---|
| D1 9-type vocabulary | `prompt.py` `EntityType`; `test_schema_enum_is_the_entity_vocabulary` |
| D2 meanings in the prompt; never the page | `_ENTITY_MEANINGS` → `_SYSTEM`; `test_system_prompt_defines_every_type_and_excludes_the_page_itself` |
| D3 off-list type → `bad_shape` | `_is_entity`; `test_bad_shape` cases `project`, `Person` |
| D4 no re-digest machinery | 3 records deleted and re-digested by hand, twice |
| D5 extraction guidance, not enforcement | `ENTITY_LIMIT` in the prompt; `test_the_entity_limit_is_guidance_so_longer_lists_still_parse` |

## Doctrine gates

- `slice verify-vt SL-007`: PHASE-01 VT-1, PHASE-02 VT-1 PASS.
- `slice conformance SL-007`: 2/2 design targets delivered, 0 undelivered.
  The undeclared list is inflated by a process slip: `493bed4` swept a
  repo-wide `ruff format` over 26 unrelated files, and `1121e6c` reverted
  them. Every reverted file was checked AST-identical before the revert.
  The per-phase registry folds the two separately, so both show up. The net
  change over the slice (`493bed4~1..HEAD`) is exactly `prompt.py`,
  `README.md` and the two digest test files, plus doctrine records.
  The gotcha is recorded as `mem.fact.panopticon.ruff-format-not-enforced`.

## VH-1 (PASS, 2026-10-02, `openai/gpt-4.1-mini`)

- **Prompt v2:** every type was in the vocabulary, with no synonym drift. But
  the model over-extracted: up to 23 entities per page, including
  keybindings, file names and alias duplicates. That led to PHASE-02.
- **Prompt v3:** at most 10 entities on the pages compared (23 → 10,
  11 → 9). Keybindings, file names, the hosting site and aliases are gone.
- **Residual small-model imprecision, accepted:**
  - a borderline page-titled tool listed as an entity;
  - keyboard layouts typed `other`;
  - `isearch` typed `concept`.

## Carried forward

- Link extraction from `content_html` (local, deterministic) is the right
  home for "what a page links to"; it is not an entity concern.
- Any vocabulary or prompt change after the backfill needs a re-digest
  mechanism or a read-time mapping (D4).
