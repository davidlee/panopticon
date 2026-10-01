# IDE-002: panopticon-digest: opt-in per-page summary, claims and embedding over the content store

Origin: `github.com:davidlee/satan.IDE-001` (raised 2026-09-29 in a SATAN
brainstorm on bookmarks, history and doctrine.engineering; moved here
2026-10-01 and closed there). Placement and egress settled by DEC-002.

## Purpose

Nothing summarises captured pages today; Readability's `excerpt` is the
nearest thing. A digest per page is the keystone for downstream consumers in
SATAN (related reading against the percept, assistive bookmark tagging, blog
link candidates, bounded links-of-links discovery). Those consumers stay in
SATAN; this item is only the derived layer.

## Shape

A batch binary, `panopticon-digest`, on its own systemd timer, **off by
default** (DEC-002: the sole network egress; capture stays network-free).
Four stages, each independently re-runnable, each output stored on its own:

1. **Gate — deterministic, local, before any egress.** Domain denylist (the
   privacy control: banking, mail, chat apps, dashboards, `127.0.0.1` never
   leave the host; optional allowlist mode), minimum size (~1.5 KB), app
   domains. A model cannot decide whether text may reach a model.
2. **Triage — jev (typesafe.ai), typed classification.** Choice `kind`
   (article / discussion / docs / listing / app / search / other) and Score
   `signal`, each with confidence. Input: url + title + first N KB (bounds
   what jev sees; state limit 32k tokens). Stored separately from the
   digest, so a taxonomy change re-runs triage for pennies without
   re-digesting. Low confidence routes to digest rather than drop.
3. **Digest — OpenRouter, structured output.** `{summary, claims[],
   entities[]}`, only for useful kinds above a `signal` threshold. Body
   truncated to a size cap.
4. **Embed — Voyage AI (candidate).** Store the model id with each vector so
   a model change is a detectable re-embed, not silent drift.

- **Key:** content SHA — the store already dedups on it, so changed content
  is a new SHA and re-processes for free. Per-URL lookup is URL → latest
  SHA via the index, **but see ISS-003**: stored URLs have their query
  stripped, so query-addressed pages collide.
- **Output:** `digest/` beside `content/`, per-SHA records for triage and
  digest plus `.jsonl` indexes, mirroring the content-store layout.
- Providers/models are config; the provider allowlist is the user's.

Simplest thing that works: text in, text out — no bespoke harness, no agent.

## Volume (surveyed 2026-10-01, 123 days of `content/`)

- 2452 captures, mean 20/day (median 18, max 58); 31 MB markdown, mean
  252 KB/day; page median 6.4 KB, p90 27 KB, p99 99 KB, max 345 KB.
- All-in ≈ 63k tokens/day; after the gate ≈ 13 pages / 45k tokens/day.
  Cost does not motivate filtering — privacy and noise do.
- App chrome (chatgpt, claude.ai, google docs/calendar/search, shopping,
  streaming, dashboards, localhost) ≈ 27% of rows, 14% of bytes. 399 rows
  under 1.5 KB. Listing pages (HN / lobste.rs / reddit fronts) recapture
  often with changing content → a new SHA each time; triage tags them.
- Jev: $0.042 / M input tokens, output free; whole-corpus backfill
  (~7.8M tokens uncapped) is cents and ~2 minutes at published rate limits;
  the SDK handles 429 backoff. Rate-limit figures differ between docs
  (100K tok/s, 40 rps) and the account terms the user relayed (250K tok/s,
  1,200 rpm) — immaterial at this volume.

## Open

- Embeddings: Voyage AI candidate (user, 2026-10-01) — pick model and
  dimension.
- Jev default data retention is unstated in its docs (zero retention is
  enterprise-only; no training on customer data). Read the DPA before
  allowlisting it (DEC-002).
- Triage taxonomy and thresholds: settle against a labelled sample of the
  real corpus, not up front.
- ISS-003: URL identity for query-addressed pages.
- Retention pairs with RSK-001 (content store unbounded).
- README + `docs/privacy.md` restatement of the invariant (DEC-002
  consequence); `docs/privacy.md` is already drifted (ISS-002).
- An ADR may be warranted when this is sliced: it would be panopticon's
  first, codifying the privacy invariant DEC-002 amends.

## Ground truth (surveyed 2026-09-29)

- `~/.local/state/behaviour/content/`: ~2379 pages, `articles.jsonl` index
  + `<sha>.json` (text/html) + `<sha>.md`; dedup by text SHA-256; heuristic
  `quality_score`. Written by `panopticon/ingest/content.py`.
