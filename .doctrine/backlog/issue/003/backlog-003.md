# ISS-003: Query stripping collapses distinct pages onto one URL (HN items, YouTube videos, searches)

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

## Problem

URL redaction strips query and fragment, deliberately and twice:
`firefox-extension/background.js` `redact()` (first pass) and
`panopticon/firefox_host/validate.py` `_redact_url()` (belt and braces).
That is a privacy control (tokens, session ids, search terms), but it also
erases page identity wherever the query *is* the identity.

## Evidence (`content/articles.jsonl`, 2026-10-01)

2452 rows, 2069 distinct URLs; 98 URLs captured more than once. Top
collisions: `www.google.com/search` ×50, `news.ycombinator.com/item` ×35,
`www.youtube.com/watch` ×33, `chatgpt.com/` ×30, `news.ycombinator.com/` ×26.
Content SHAs stay distinct, so the store itself is fine; anything keyed or
looked up by URL is not.

## Impact

IDE-002's per-URL lookup (URL → latest SHA) returns an arbitrary HN item or
video. Same for any consumer joining tab segments to content by URL.

## Fix direction (undecided)

- Per-domain allowlist of identifying params kept through redaction
  (`news.ycombinator.com: id`, `youtube.com: v`); everything else still
  stripped. Small, explicit, privacy-preserving by default.
- Rejected-ish: keyed hash of the full URL — preserves identity but not
  readability, and a hash of a search query is still a fingerprint.
- Must change both redaction sites together (and their tests); historical
  rows stay collided.
