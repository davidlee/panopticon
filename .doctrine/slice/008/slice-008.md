# digest: privacy-surface flag for gate audit

## Context

Originates from IDE-004 (`references --role originates_from`). SL-006 VH-1
sent a LinkedIn compose page (the user's own draft) past the gate. The miss
was fixed in `DEFAULT_DENY`, but the gate has no feedback loop.

IDE-004 placed the flag in stage-2 triage, to avoid a digest schema change
forcing a re-digest. Triage does not exist, and only 3 digest records do,
so before the backfill a schema change costs nothing (user, 2026-10-02:
digest schema, now).

## Scope & Objectives

- The digest reply gains a closed-enum `private_surface` field: `none`, or
  the reason the page looks private or pre-publication.
- `PROMPT_VERSION` 3 → 4; the prompt defines each reason and says public
  user-generated content is `none`.
- A local, read-only audit (`panopticon-digest --audit`) lists flagged
  records the current gate would still pass, with candidate `deny` entries.
- Operational: delete the 3 version-3 records and re-digest them.

## Non-Goals

- Gating on the flag. It is detection after egress; a model never decides
  whether text may reach a model (SL-006).
- Writing `deny` entries automatically. The audit proposes; the user edits
  the config.
- Stage-2 triage, re-digest machinery (SL-007 D4).

## Summary

Pure-layer change in `panopticon/digest/prompt.py`, a read-only audit mode
in `panopticon/digest/__main__.py`, tests, and the README.

## Follow-Ups

- If triage lands and filters pages out of the digest, those pages are no
  longer flagged; revisit placement then.
