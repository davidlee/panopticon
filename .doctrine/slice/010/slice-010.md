# content handoff: host replies with the captured page's path

## Context

Originates from IMP-004. Its first part shipped as `just content-path [URL]`
(`tools/content_path.py`): the path of a captured page's Markdown, found by
looking it up afterwards. This slice is the second part: hand the path back
at the moment of the send, so it can be pasted straight into an agent.

Today, as found while scoping (2026-10-25):
- The context-menu item "Extract page content for Panopticon" and the 30 s
  dwell timer both call `injectContentScript`; the resulting
  `browser_content_extracted` message carries nothing that says which one
  triggered it.
- The native port is one-way. The extension never registers
  `port.onMessage`; the host never writes to stdout (`protocol.write_message`
  exists but only tests use it).
- The host computes the hash and path in `ContentStore.store()`, but returns
  `None` on a duplicate (unchanged page sent again), and drops errors and
  empty content with a debug log. Its success log goes to Firefox's stderr.
- The extension has no `clipboardWrite` or `notifications` permission.
  Adding either means a manifest version bump and re-signing (`just sign`).

## Scope & Objectives

- **Mark manual sends.** The extension tags each extraction with its trigger
  (manual vs dwell); the host validates the field.
- **Reply on the port.** After a manual send, the host writes one framed
  reply: the `.md` path and hash on success, including the duplicate case;
  a reason on failure (extraction error, empty or short content). No reply
  for dwell extractions.
- **Surface it in Firefox.** The extension handles the reply: copy the path
  to the clipboard and/or show a notification (design decides; see OQ-1).
- **Reply channel general enough for IDE-003**, which wants the host to push
  settings to the extension over the same port. Shape the message envelope
  so a second message kind fits without rework; do not build IDE-003.
- Tests both ends: host reply framing and routing (Python); the extension's
  existing parity/behaviour tests as precedent.
- Docs: `firefox-extension/README.md` (the port is no longer one-way),
  `docs/privacy.md` if the clipboard is touched.

## Open questions (for design)

- OQ-1: clipboard, notification, or both? Clipboard is the point, but a
  silent clipboard write is surprising; a notification alone is not
  pasteable.
- OQ-2: reply payload: `.md` path only, or also the `.json` path and hash?
- OQ-3: does the reply correlate to the request (a request id), or is "last
  manual send" enough given one context-menu click at a time?
- OQ-4: should `store()` return the entry on a duplicate instead of `None`
  (behaviour change to a shared seam), or should the host derive the path
  itself from the hash?
- OQ-5: sequence with IDE-003, or leave IDE-003 to reuse the envelope later?

## Non-Goals

- IDE-003 itself (host config, redaction push).
- Changing what is extracted, the dwell timer, or the content store layout.
- Retention (RSK-001) and the privacy-doc drift on page bodies (ISS-002).

## Summary

Extension: trigger field, `port.onMessage` handler, one permission, version
bump. Host: validate the field, write a framed reply after manual sends.
Small on both sides; the risk is in the envelope shape and the permission
and privacy wording.

## Follow-Ups

- IDE-003 can reuse the reply envelope for settings push.
