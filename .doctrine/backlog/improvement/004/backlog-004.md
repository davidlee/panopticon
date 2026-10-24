# IMP-004: Hand a captured page to an agent: content-path lookup, then host replies with the path

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-10-25: "when I send a page to panopticon via the browser
extension, how can I get a reference to the file on disk to hand to an agent?"

## Problem

The context-menu send ("Extract page content for Panopticon") reaches
`ContentStore.store()`, which writes
`content/<hash[:2]>/<hash>.{md,json}` and appends to `content/articles.jsonl`.
Nothing reports the path back: the native port is one-way, and the host's
`content stored: hash=…` log goes to Firefox's stderr. Finding the file means
hand-rolling `jq` over the index, with traps:

- re-sending an unchanged page rewrites the shard files but appends no index
  row, so "last index row" is not "last sent";
- 30 s dwell auto-extraction shares the index, so the newest row may not be
  the page you sent;
- stored URLs are redacted (query/fragment stripped bar identity params), so
  a pasted URL does not match verbatim.

## Shape

1. **Lookup (done first).** `just content-path [URL]` prints the `.md` path
   of the newest capture, or of the given page. Newest = latest `.md` mtime
   (survives the dedup trap); the URL goes through the host's redaction
   before matching.
2. **Host replies with the path.** After a manual send the host posts
   `{hash, path}` back on the native port; the extension copies the path to
   the clipboard and/or shows a notification. Needs the extension to mark
   manual vs dwell extraction (only reply to manual), and the host to write
   to stdout per the native-messaging framing. Shares the "port becomes
   bidirectional" step with IDE-003 — sequence or combine the two. Protocol
   change across both ends: needs a slice.
