# Design SL-010: content handoff: host replies with the captured page's path

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, IMP-004); doc-local refs bare — OQ-1 (§6), D1 (§7), R1 (§10). -->

## 1. Design Problem

A manual "Extract page content for Panopticon" click stores the page, but the
`.md` path only comes back through a later lookup (`just content-path`,
IMP-004 part one). Hand the path back at the moment of the send: the host
replies on the native port; the extension copies the path to the clipboard
and confirms with a notification.

## 2. Current State

- `background.js`: the context-menu click and the 30 s dwell timer both call
  `injectContentScript(tabId)`, which injects `Readability.js` + `content.js`
  as files (no arguments can be passed). `content.js` answers with a runtime
  message `{type: "content_extracted", …}`; the `onMessage` listener forwards
  it to the host as `browser_content_extracted`. Nothing records which
  trigger caused it.
- The port is one-way: no `port.onMessage` listener; the host never writes
  to stdout. `protocol.write_message` exists, used only by tests.
- `_handle_content_extracted` (host `__main__.py`) drops `error` and
  empty text/HTML with a debug log, else calls `ContentStore.store()`.
- `ContentStore.store()` writes `<hash>.json` and `<hash>.md` *before* the
  duplicate check, then returns `None` on a duplicate. So after every store
  the `.md` exists at `shard_path(root, content_hash(text), ".md")` — both
  functions public.
- Short content is never rejected: `_MIN_TEXT_LENGTH` only lowers the
  quality score. The only failures are `error` and empty content.
- `browser_content_extracted` never reaches the raw JSONL tier, so a new
  field on it is not persisted anywhere.
- Manifest 0.2.3; no `clipboardWrite` or `notifications` permission.
- No JS test harness. Extension coverage is Python reading `background.js`
  as text (`tests/test_firefox_validate.py`, the redaction parity test).

## 3. Forces & Constraints

- Stdout is the wire: any stray write corrupts the stream.
- Firefox may close the port at any time; a write can hit a broken pipe.
- The reply arrives after the user gesture has ended, so the clipboard write
  needs the `clipboardWrite` permission.
- A permission change means a version bump and `just sign`.
- An older or unsigned extension must keep working against a new host.
- IDE-003 will push settings over the same port.

## 4. Guiding Principles

- Ride existing seams: no change to `ContentStore.store()`.
- Pure core, thin shell: the reply is built by a pure function from an
  outcome; only `run_loop` writes.
- Reply only when asked: dwell traffic stays one-way.

## 5. Proposed Design

### 5.1 System Model

```
 menu click ──► background.js ── pendingManual[tabId] = id ──► inject content.js
                                                                    │
            ┌─────────── runtime msg {type:content_extracted} ◄─────┘
            ▼   (sender.tab.id ∈ pendingManual → trigger=manual, id)
     port.postMessage {event: browser_content_extracted, trigger, id, …}
            │
            ▼ host run_loop
     validate (trigger ∈ {manual, dwell}; absent → dwell)
     _handle_content_extracted → Outcome (stored hash | failure reason)
     trigger == manual → write_message(stdout, content_path_reply(id, outcome))
            │
            ▼ port.onMessage → dispatch on `type`
     "content_path" ok   → clipboard.writeText(path); notify "Path copied: …"
     "content_path" fail → notify reason (clipboard untouched)
     unknown type        → ignore (log)
```

### 5.2 Interfaces & Contracts

**Request** (extension → host), additions to `browser_content_extracted`:

| field     | type                    | rule                                      |
|-----------|-------------------------|-------------------------------------------|
| `trigger` | `"manual"` \| `"dwell"` | optional; absent → `dwell`; other → drop  |
| `id`      | string                  | required when `trigger == "manual"`       |

**Reply envelope** (host → extension): a JSON object with a `type` string.
The extension dispatches on `type` and ignores unknown values. IDE-003 adds
`type: "settings"` with no change here.

```json
{"type": "content_path", "id": "<echoed>", "ok": true,
 "path": "/…/content/ab/ab12….md", "hash": "ab12…"}
{"type": "content_path", "id": "<echoed>", "ok": false,
 "reason": "extraction_error" | "empty_content"}
```

- Success covers the duplicate case (path from `content_hash` +
  `shard_path`; the files exist because `store()` rewrote them).
- The extraction's own error string is not echoed; `reason` is a closed set.
- Exactly one reply per valid manual request. No reply for dwell, nor for a
  message dropped by validation (no trustworthy `id` to answer).

**Host functions**

- `_handle_content_extracted(ct_root, ts, fields) -> Outcome` — returns
  instead of only logging. `Outcome` = stored `(hash, md_path)` or a
  failure `reason`.
- `content_path_reply(id, outcome) -> dict` — pure.
- `run_loop(stdin, store, *, reply: BinaryIO, record_file_urls=False)` —
  writes the reply for manual triggers; `_cmd_run` passes
  `sys.stdout.buffer`. `BrokenPipeError`/`OSError` on write: log a warning,
  keep reading (the next stdin EOF ends the loop as today).

**Extension**

- `pendingManual: Map<tabId, id>` set on menu click, consumed on the
  matching `content_extracted` (`sender.tab.id`). `id` from
  `crypto.randomUUID()`.
- `port.onMessage` registered in `connect()`; handler dispatches on `type`.
- Permissions `clipboardWrite`, `notifications`; version 0.3.0.

### 5.3 Data Model

None persisted. `trigger` and `id` are wire-only; `ContentStore` does not
see them.

## 6. Open Questions

None open. OQ-1…OQ-5 from the scope are settled in §7.

## 7. Decisions

- **D1 (OQ-1) Both clipboard and notification.** Success copies the path
  and notifies "Path copied: <path>", so the write is never silent. Failure
  notifies the reason and leaves the clipboard alone. (User, 2026-10-27.)
- **D2 (OQ-2) Payload: `.md` path and hash.** The `.json` path is derivable;
  the hash aids debugging and matches the index.
- **D3 (OQ-3) Correlate with an echoed `id`.** Cheap, and each reply is
  self-describing; "last manual send" breaks under two quick clicks.
  Trigger is identified per tab because `content.js` takes no arguments.
- **D4 (OQ-4) Host derives the path; `store()` unchanged.** The files exist
  after every store, so `content_hash` + `shard_path` gives the path on the
  duplicate case without changing a shared seam.
- **D5 (OQ-5) Do not sequence with IDE-003.** The `type`-keyed envelope is
  enough for it to add a kind later.
- **D6 Absent `trigger` = dwell.** An older extension keeps working; an
  unknown value is dropped. (User, 2026-10-27.)
- **D7 Reply field is `type`, not `event`.** Host→extension messages are not
  events; `type` matches the extension's internal runtime messages.
- **D8 Extension verified manually plus static checks.** No JS harness.
  (User, 2026-10-27.)

## 8. Impact & Changes

- `panopticon/firefox_host/validate.py` — `trigger`/`id` rules.
- `panopticon/firefox_host/__main__.py` — `Outcome`, reply builder,
  `run_loop` reply stream; module docstring ("we don't reply") updated.
- `firefox-extension/background.js` — `pendingManual`, tagging,
  `port.onMessage` dispatch, clipboard + notification.
- `firefox-extension/manifest.json` — two permissions, 0.3.0.
- `firefox-extension/README.md` — the port is two-way; reply contract.
- `docs/privacy.md` — the extension *writes* the clipboard on a manual send
  (never reads it).
- Tests: `tests/test_firefox_host_main.py`, `tests/test_firefox_validate.py`.

## 9. Verification

- VT host: manual success → one framed reply with path + hash, path exists.
- VT host: manual duplicate (same text twice) → success reply, same path.
- VT host: manual `error` → `reason: extraction_error`; empty →
  `empty_content`.
- VT host: dwell and absent trigger → no bytes on the reply stream.
- VT host: reply stream raising `BrokenPipeError` → loop continues, later
  events still stored.
- VT validate: unknown `trigger` dropped; manual without `id` dropped.
- VT static: manifest has both permissions and version > 0.2.3;
  `background.js` trigger literals match the validator's set; it registers
  `port.onMessage`.
- VH: after `just sign`, manual extract → notification + pasteable path;
  repeat on the same page → same path; dwell → no notification.

## 10. Risks

- **R1 Clipboard in a background page.** Firefox allows
  `navigator.clipboard.writeText` in the background with `clipboardWrite`;
  if it fails at VH, fall back to notification-only and record it.
- **R2 Stray stdout writes.** Any print or library write to stdout corrupts
  the wire. Logging already goes to stderr; tests assert the reply stream
  holds only framed messages.
- **R3 Pending entry leaks.** A manual injection that never answers (page
  closed, injection failed) leaves a `pendingManual` entry; clear it on the
  injection's `catch` and on tab removal.
