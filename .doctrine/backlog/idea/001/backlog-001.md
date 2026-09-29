# IDE-001: Ingest Firefox bookmarks: places.sqlite backfill plus live bookmarks API, fetch pages not yet captured

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-09-29 from the SATAN side (satan IDE-001..005: page digests,
related reading, tagging, blog link suggestions, links-of-links). Bookmarks are
perception, so ingest belongs here (satan ADR-001 / POL-001).

## Ground truth (2026-09-29)

- Nothing reads bookmarks. `firefox-extension/manifest.json` lacks the
  `bookmarks` permission; `docs/privacy.md:51` promises no `history.search`.
- Default profile `~/.config/mozilla/firefox/ez06zp0k.default`: `places.sqlite`
  57 MB, live WAL. 417 bookmarks, 66 folders, 345 tags / 640 applications, no
  keywords or descriptions. 122k history visits since 2025-03-01.
- `ingest/extractor.py` (Trafilatura fetch+extract) exists but is uncalled.

## Shape

- **Backfill:** read a copy of `places.sqlite` (live file is locked/WAL; copy
  DB + WAL, or open `immutable=1`, which misses WAL-resident rows).
- **Live:** `bookmarks.onCreated/onChanged/onRemoved` in the extension →
  native host → raw event stream.
- **Fetch:** bookmark URLs with no content-store row → extractor → the existing
  content store (same dedup, same `.md`).

## Open

- Privacy doc and permission change (history access is a new promise; see
  ISS-002).
- Tags/folders as event fields or a separate bookmarks index.
