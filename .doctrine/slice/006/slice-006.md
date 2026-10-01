# panopticon-digest: opt-in page digest over the content store

## Context

Originates from IDE-002 (`references --role originates_from`). Placement and the
network-egress exception are settled by DEC-002 (`references --role concerns`):
`panopticon-digest` is the **sole** network egress, a separate binary with its
own unit and timer, off by default; capture stays network-free.

Nothing summarises captured pages today; Readability's `excerpt` is the nearest
thing. A per-page digest is the keystone for downstream consumers in SATAN
(related reading, bookmark tagging, link candidates). Those consumers stay in
SATAN; this slice is only the derived layer.

Ground truth (2026-10-01):

- Content store: `panopticon/ingest/content.py` (`ContentStore`). Layout
  `content/articles.jsonl` (index: `content_hash`, `url`, `domain`, `title`,
  `extractor`, `captured_at`, `quality_score`) + `content/<sha[:2]>/<sha>.{json,md}`.
  Dedup by SHA-256 of `text_content`; the `.json` record carries `length`,
  `text_content`, `excerpt`.
- `domain` is the lowercased hostname of the redacted URL
  (`firefox_host/validate.py`). Since ISS-003 (resolved, 899b6b8) the URL keeps
  per-host identity params (HN `id`, YouTube `v`), so URL → latest SHA is a
  usable page identity.
- Precedent for a batch derived layer: `panopticon-segmentize`
  (`segmentizer/__main__.py`, `systemd/segmentizer.{service,timer}`) —
  single-shot, `--root`/`--now`/`-v`, atomic writes, retention at the end.
- No config file exists anywhere in panopticon (IDE-003 proposes one for the
  firefox host). The digest needs config (gate lists, providers, models,
  thresholds) and secrets (API keys).
- Volume: ~20 captures/day; ~13 pages / ~45k tokens/day after the gate. Cost
  does not motivate filtering — privacy and noise do.

## Scope & Objectives

A new console script `panopticon-digest` with four stages, each independently
re-runnable, each output stored separately and keyed by content SHA:

1. **Gate** — deterministic, local, before any egress: domain denylist (optional
   allowlist mode), minimum size, app domains. Pure function of the index entry
   and config. A model never decides whether text may reach a model.
2. **Triage** — typed classification (`kind`, `signal`, each with confidence)
   over url + title + the first N KB. Stored apart from the digest so a taxonomy
   change re-runs triage alone.
3. **Digest** — structured `{summary, claims[], entities[]}` for useful kinds
   above a `signal` threshold; body truncated to a size cap.
4. **Embed** — a vector per digest, stored with its model id so a model change
   is a detectable re-embed.

Plus:

- `digest/` beside `content/`: per-SHA records per stage + `.jsonl` indexes,
  mirroring the content-store layout.
- Config + secrets loading; providers and models are config; the provider
  allowlist is the user's.
- systemd service + timer, shipped **disabled**.
- README and `docs/privacy.md` restate the invariant per DEC-002: capture never
  touches the network; `panopticon-digest` is the sole opt-in egress.

## Non-Goals

- Downstream consumers (related reading, tagging, link discovery) — SATAN.
- Content-store retention (RSK-001). Digest records follow content records;
  this slice does not add content retention.
- The firefox-host config file and redaction push (IDE-003). A config loader
  built here should be reusable by it, not shaped for it.
- Local inference.
- Fixing the wider `docs/privacy.md` drift (ISS-002) beyond the egress
  statement this slice must add.

## Summary

Opt-in, offline-by-default batch job: local gate → remote triage → remote
digest → remote embedding, over the existing content store, keyed by content
SHA so re-captures of unchanged pages cost nothing.

## Follow-Ups

- Settle the triage taxonomy and thresholds against a labelled sample of the
  real corpus.
- Read the jev (typesafe.ai) DPA before it joins the provider allowlist.
- Pick the embedding model and dimension (Voyage AI candidate).
- Consider panopticon's first ADR: the privacy invariant as amended by DEC-002.
