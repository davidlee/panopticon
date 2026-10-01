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

## Agreed design (user, 2026-10-01)

Worked directly off this item on an agreed sketch (no slice).

- One per-host map of identity params, baked in:
  `news.ycombinator.com: [id]`, `www.youtube.com|youtube.com|m.youtube.com: [v]`.
  For a listed host, redaction keeps only those params (sorted) and still
  drops the fragment and everything else; unlisted hosts are unchanged.
- Search queries (`google.com/search?q=`, `youtube.com/results`, amazon `s`)
  stay stripped — low value, not merely private (user).
- Both redaction sites change: `validate.py::_redact_url` (host) and
  `background.js::redact` (extension). The JS constant is strict JSON; a
  Python parity test parses it out of `background.js` and asserts equality.
- Configurable rather than baked was considered and deferred: there is no
  host config surface and the extension strips before the host sees the
  URL — see IDE-003.
- Docs: `docs/schema.md`, `docs/privacy.md`. Extension version bump; the
  rebuilt/signed extension is the user's deploy step. Historical rows stay
  collided.

## Resolution (2026-10-01)

- Host: `IDENTITY_PARAMS` + `_identity_query` in `validate.py`.
- Extension: same map + `identityQuery` in `background.js`; manifest 0.2.3.
- Also fixed a second instance in the extension: `isUrlExtracted` (the
  per-session dwell-extraction dedup) compared query-stripped URLs, so after
  the first HN item / video in a session every other one was treated as
  already extracted and never captured. It now compares `redact(url)` — the
  same canonical form `recordExtractedUrl` stores.
- Tests: kept/stripped tables plus the JS↔Python parity test
  (`tests/test_firefox_validate.py`). Docs: README, extension README,
  `docs/schema.md`, `docs/privacy.md`.
- Deploy (user): `just package-extension`, sign, install 0.2.3; redeploy
  the host via the flake. Neither recovers params the 0.2.2 extension
  already stripped — historical rows stay collided.
