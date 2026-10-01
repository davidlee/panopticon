# digest: closed entity-type vocabulary

## Context

Originates from IMP-002 (`references --role originates_from`). SL-006's
VH-1 run showed `entities[].type` drifting under a free-text prompt
(`software` vs `project`; invented types such as `hardware audio device`).
Downstream SATAN consumers (tagging, related reading) group by type, so
drift defeats them.

Only 3 digest records exist (VH-1). Fixing the vocabulary before the
backfill makes migration trivial.

## Scope & Objectives

- A closed, 9-value entity-type vocabulary enforced by the strict
  `json_schema` and checked by `parse_digest`.
- Per-type definitions in the system prompt; the page itself is never an
  entity of its own digest.
- `PROMPT_VERSION` 1 → 2.
- Operational: delete the 3 version-1 records and re-digest them.

## Non-Goals

- Triage (stage 2) and its page-`kind` taxonomy: a different vocabulary
  (pages, not the things they name). No coupling.
- Link extraction from `content_html`: local, deterministic, separate.
- Version-aware re-digest machinery (a done record stays done regardless
  of `prompt_version`).

## Summary

Small, pure-layer change in `panopticon/digest/prompt.py` plus its tests and
the README's record description.

## Follow-Ups

- If a vocabulary change is ever needed after the backfill, it will need a
  re-digest mechanism (or read-time mapping); out of scope here.
