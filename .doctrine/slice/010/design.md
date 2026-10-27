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
  as files. `content.js` is a self-running IIFE that answers with a runtime
  message `{type: "content_extracted", …}`; the `onMessage` listener forwards
  it to the host as `browser_content_extracted` from two send sites (error,
  success). Nothing records which trigger caused it, and two injections on
  one tab (dwell in flight, then a click) produce indistinguishable messages.
- `scripting.executeScript` also accepts `{func, args}` and resolves with
  each frame's return value; neither is used today.
- The port is one-way: no `port.onMessage` listener; the host never writes
  to stdout. `protocol.write_message` exists, used only by tests; it raises
  `ProtocolError` above 1 MiB.
- `run_loop` catches `ProtocolError` only around reads and
  `ValidationError` around validation. A `ValidationError` drops the whole
  event. Nothing guards `_handle_content_extracted`: an exception in
  `ContentStore.store()` (markdownify, disk) ends the host process.
- `_handle_content_extracted` drops `error` and empty text/HTML with a debug
  log, else calls `ContentStore.store()`.
- `ContentStore.store()` writes `<hash>.json` and `<hash>.md` *before* the
  duplicate check, then returns `None` on a duplicate. So after every
  successful store the `.md` exists at
  `shard_path(ct_root, content_hash(text), ".md")`, where `run_loop` builds
  `ct_root = content_dir(root=store.root)`.
- Short content is never rejected: `_MIN_TEXT_LENGTH` only lowers the
  quality score.
- `browser_content_extracted` never reaches the raw JSONL tier, so a new
  field on it is not persisted anywhere.
- `connect()` resets the reconnect backoff as soon as `connectNative`
  returns, so a host that dies at start respawns every second (pre-existing;
  out of scope).
- Manifest 0.2.3; no `clipboardWrite` or `notifications` permission.
- No JS test harness. Extension coverage is Python reading `background.js`
  as text: the parity test `json.loads` a strict-JSON `const` literal
  (`tests/test_firefox_validate.py`).
- Nine tests call `run_loop(stdin, store)`.

## 3. Forces & Constraints

- Stdout is the wire: any stray write corrupts the stream.
- Firefox may close the port at any time; a write can hit a broken pipe.
- The reply arrives after the user gesture has ended, so the clipboard write
  needs the `clipboardWrite` permission and can still be refused.
- A permission change means a version bump and `just sign`.
- An older or unsigned extension must keep working against a new host; no
  new rule may lose an article that is stored today.
- IDE-003 will push settings over the same port.
- Behaviour preservation: the existing host suites stay green unchanged.

## 4. Guiding Principles

- Ride existing seams: no change to `ContentStore.store()`.
- Pure core, thin shell: the reply is built by a pure function from an
  outcome; only `run_loop` writes.
- Reply only when asked: dwell traffic stays one-way.
- Every manual click ends in exactly one user-visible notification.

## 5. Proposed Design

### 5.1 System Model

Extraction becomes a request/response inside the extension: the background
awaits `executeScript`'s return value, so the trigger is known from the
call site, not inferred from a later message.

```
 menu click / dwell timer
        │ extract(tabId, trigger)
        ▼
 executeScript files [Readability.js, content.js]   (defines panopticonExtract)
 executeScript {func: () => panopticonExtract()}  ─► article | {error}
        │ (result returned to the awaiting call; trigger in closure)
        ▼
 trigger == manual: id = crypto.randomUUID(); pending[id] = timer(10 s)
 send {event: browser_content_extracted, trigger, id?, …article}
        │
        ▼ host run_loop
 validate: trigger normalised (manual|dwell; anything else → dwell);
           manual needs a well-formed id, else treated as dwell
 outcome = _handle_content_extracted(...)   (never raises)
 manual → write_message(reply, content_path_reply(id, outcome))
        │
        ▼ port.onMessage → dispatch on `type`
 "content_path": clear pending[id];
     ok   → try await clipboard.writeText(path) → notify "path copied"
                                      catch    → notify "captured; copy failed"
     fail → notify reason
 unknown type → ignore (log)
 pending timer fires / port disconnects with pending ids → notify "no reply"
```

### 5.2 Interfaces & Contracts

**Request** (extension → host), additions to `browser_content_extracted`:

| field     | type                    | rule                                              |
|-----------|-------------------------|---------------------------------------------------|
| `trigger` | `"manual"` \| `"dwell"` | absent, null or unknown → `dwell`                  |
| `id`      | string                  | manual only; `^[A-Za-z0-9-]{1,64}$`, else → dwell |

Normalisation never raises `ValidationError`: the article is stored in every
case where it is stored today; a malformed manual request only loses its
reply. Both fields are stripped before `fields` reach `ContentStore`.

**Reply envelope** (host → extension): a JSON object with a `type` string.
The extension dispatches on `type` and ignores unknown values. IDE-003 adds
`type: "settings"` with no change here.

```json
{"type": "content_path", "id": "<echoed>", "ok": true,
 "path": "/abs/…/content/ab/ab12….md", "hash": "ab12…"}
{"type": "content_path", "id": "<echoed>", "ok": false,
 "reason": "extraction_error" | "empty_content" | "store_failed"}
```

- Success covers the duplicate case.
- `reason` is a closed set; the extraction's error string is not echoed.
- One reply per manual request that passes validation.

**Host functions**

- `_handle_content_extracted(ct_root, ts, fields) -> Outcome` — never
  raises. `Outcome` is `Stored(hash, md_path)` with `md_path` the absolute
  `shard_path(ct_root, hash, ".md")`, or `Failed(reason)`. A store exception
  is logged (stderr) and becomes `Failed("store_failed")`; this also stops a
  bad page from ending capture, dwell included.
- `content_path_reply(id, outcome) -> dict` — pure; copies `md_path` from
  the outcome, never rebuilds it.
- `run_loop(stdin, store, *, reply: BinaryIO | None = None,
  record_file_urls=False)` — no `reply` → no writes, so existing call sites
  are unchanged. `_cmd_run` passes `sys.stdout.buffer`. `OSError` (incl.
  `BrokenPipeError`) or `ProtocolError` on write: log a warning, keep
  reading.

**Extension**

- `content.js` defines `panopticonExtract()` returning the article object or
  `{error}`; it no longer posts a runtime message. The `runtime.onMessage`
  listener for `content_extracted` is removed.
- `extract(tabId, trigger)` replaces `injectContentScript`; it builds the
  payload once (one send site) with the trigger tag spread in.
- `const TRIGGERS = ["manual", "dwell"];` — strict JSON, for the parity test.
- `pending: Map<id, timeoutId>`; entry deleted on reply, timeout or port
  disconnect, each of which notifies at most once. A manual extraction that
  fails before sending (injection rejected, redaction null) notifies
  directly and sends nothing.
- `port.onMessage` registered in `connect()`.
- Notifications carry fixed text (and the failure reason), never the path
  or page title: notification centres mirror to lock screens.
- Permissions `clipboardWrite`, `notifications`; version 0.3.0.

### 5.3 Data Model

None persisted. `trigger` and `id` are wire-only.

## 6. Open Questions

None open. OQ-1…OQ-5 from the scope are settled in §7.

## 7. Decisions

- **D1 (OQ-1) Both clipboard and notification.** Success copies the path
  and notifies; failure notifies the reason and leaves the clipboard alone.
  (User, 2026-10-27.) The notification reports what actually happened to the
  clipboard write (awaited).
- **D2 (OQ-2) Payload: `.md` path and hash.** The `.json` path is derivable;
  the hash aids debugging and matches the index.
- **D3 (OQ-3) Correlate with an echoed `id`; attribute the trigger at the
  call site.** The background awaits `executeScript`'s result, so it knows
  which call produced which article; no per-tab inference, no dwell/manual
  race. The `id` pairs reply with request across the port.
- **D4 (OQ-4) Host derives the path; `store()` unchanged.**
- **D5 (OQ-5) Do not sequence with IDE-003.** The `type`-keyed envelope is
  enough for it to add a kind later.
- **D6 Lenient trigger.** Absent, null or unknown `trigger` → dwell; manual
  with a malformed `id` → dwell. Revises the first draft, which dropped
  unknown values: a `ValidationError` drops the whole article, which breaks
  the compatibility constraint. (User chose "absent = dwell", 2026-10-27;
  the unknown-value case is revised on review evidence.)
- **D7 Reply field is `type`, not `event`.** Host→extension messages are not
  events; `type` matches the extension's runtime messages.
- **D8 Extension verified manually plus static checks.** No JS harness.
  (User, 2026-10-27.)
- **D9 Guard the store.** `_handle_content_extracted` never raises; failures
  become `store_failed`. Fixes a pre-existing crash path as a side effect.
- **D10 Every manual click notifies exactly once** — reply, 10 s timeout, or
  port disconnect, whichever first.

## 8. Impact & Changes

- `panopticon/firefox_host/validate.py` — trigger/id normalisation.
- `panopticon/firefox_host/__main__.py` — `Outcome`, store guard, reply
  builder, optional reply stream; docstrings ("we don't reply") updated.
- `firefox-extension/content.js` — defines `panopticonExtract()`.
- `firefox-extension/background.js` — `extract()`, `TRIGGERS`, `pending`,
  `port.onMessage` dispatch, clipboard + notification; `onMessage` listener
  removed.
- `firefox-extension/manifest.json` — two permissions, 0.3.0.
- `firefox-extension/README.md` — the port is two-way; reply contract.
- `docs/privacy.md` — the extension *writes* the clipboard on a manual send
  (never reads it); notifications carry no page data.
- Tests: `tests/test_firefox_host_main.py`, `tests/test_firefox_validate.py`.

## 9. Verification

- VT host: manual success → one framed reply; `path` absolute, under the
  run's `ct_root`, exists.
- VT host: manual duplicate (same text twice) → success reply, same path.
- VT host: manual `error` → `extraction_error`; empty → `empty_content`;
  `store()` raising → `store_failed`, loop continues.
- VT host: dwell, absent, null and unknown trigger → stored, no reply bytes.
- VT host: manual with oversized or ill-formed `id` → stored, no reply.
- VT host: reply stream raising `BrokenPipeError` → loop continues, later
  events still stored.
- VT host: existing `run_loop(stdin, store)` tests pass unchanged.
- VT static: manifest has both permissions and version > 0.2.3;
  `TRIGGERS` in `background.js` equals the validator's set; `background.js`
  registers `port.onMessage`.
- VH: after `just sign` — manual extract → notification + pasteable path;
  same page again → same path; dwell → no notification; host stopped →
  "no reply" notification.

## 10. Risks

- **R1 Clipboard refusal.** `writeText` from the background page may be
  refused (focus, compositor). Handled: the notification says the copy
  failed. If it always fails at VH, record it and revisit.
- **R2 Stray stdout writes.** Any print or library write to stdout corrupts
  the wire. Logging already goes to stderr; tests assert the reply stream
  holds only framed messages.
- **R3 Event-page suspension.** `pending` is in memory. The open native port
  keeps the event page alive; if it is suspended anyway, the reply is
  dropped silently. Accepted: the path is still recoverable with
  `just content-path`.
