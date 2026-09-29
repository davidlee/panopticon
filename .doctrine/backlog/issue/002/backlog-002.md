# ISS-002: privacy.md and schema.md deny page-body capture, which browser_content_extracted now does

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Found 2026-09-29.

- `docs/privacy.md:49-52` — "Does not capture page bodies… DOM scraping".
- `browser.local.md:19-35,517-538` — "Avoid DOM text extraction".
- `docs/schema.md:84-105` — event list omits `browser_content_extracted`.

The code does capture bodies: `firefox-extension/background.js:143-223`
(30 s dwell or context menu → Readability + `content.js` → full `textContent`
and `contentHtml`) → `firefox_host/__main__.py:83-84,108-143` →
`ingest/content.py` content store.

Update privacy.md (what is captured, when, where, retention — see RSK-001) and
schema.md (event shape + content store layout).
