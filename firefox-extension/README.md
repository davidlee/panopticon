# Panopticon Firefox capture

A minimal Firefox WebExtension (MV3) that records active-tab attention
signals — which URL was active, for how long, in which window — and
forwards them through a native messaging host into the panopticon
behavioural event pipeline.

The extension is the dumb producer; the segmentizer downstream owns the
meaning (segments, joins with Sway focus, histograms). See
`../browser.local.md` for the full design.

## What it captures

- `browser_snapshot` on startup
- `browser_tab_active` on tab switch / window focus
- `browser_tab_updated` for title / status / audible changes on the active tab
- `browser_navigation` (kind `committed` or `history_state_updated`) for real and SPA navigation
- `browser_window_focus` when Firefox itself gains or loses focus
- `browser_idle_state` when the system idle state changes

## What it never captures

- Page bodies, form contents, typed input, password fields
- Cookies, headers, request/response bodies
- Full history; no DOM scraping; no screenshots
- Private (incognito) windows or tabs — dropped before emission
- `about:`, `moz-extension:`, `chrome:`, `resource:`, `view-source:`,
  `data:`, `blob:`, `javascript:`, and `file:` URLs
- Query strings and fragments — stripped before emission, again at the host

## Install

### 1. Install the native messaging host

The Python host ships in the panopticon package. From the repo root:

```bash
uv pip install -e .
panopticon-firefox-host install-manifest
```

This writes `~/.mozilla/native-messaging-hosts/panopticon_firefox.json`
pointing at the absolute path of `panopticon-firefox-host` on your
`PATH`. The manifest allowlists this extension's ID
(`panopticon-firefox@panopticon.local`).

To preview without writing:

```bash
panopticon-firefox-host install-manifest --print
```

### 2. Load the extension into Firefox

Until the extension is signed, load it as a temporary add-on:

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on**.
3. Pick `firefox-extension/manifest.json` from this repo.

The temporary add-on persists only until Firefox restarts; reload after
every restart, or sign the extension for permanent install.

### 3. Confirm events are flowing

After browsing for a minute or two:

```bash
tail -F ~/.local/state/behaviour/raw/firefox-$(date +%F).jsonl
```

Each line is one event in the panopticon schema (`v`, `ts`, `source`,
`event`, plus fields).

## Manual test procedure

Mirrors `../browser.local.md`:

1. Start Firefox with the extension loaded.
2. Visit URL A, wait >30 s, switch to URL B.
3. Switch to another desktop app, then back to Firefox.
4. Open a GitHub SPA route (e.g. `/repo` → `/repo/pulls`).
5. Play and pause an audible tab.
6. Open a private window — confirm nothing is recorded.
7. Close Firefox.

Then run the segmentizer:

```bash
panopticon-segmentize -v
```

Expected:

- `~/.local/state/behaviour/segments/browser-$(date +%F).jsonl`
  contains a `browser_tab_segment` per visited URL.
- `~/.local/state/behaviour/histograms/daily-$(date +%F).json` contains
  a `per_domain_seconds` bucket.

## Notes

- The host name is `panopticon_firefox` (the underscore is required by
  Firefox's native-messaging naming rules).
- The extension reconnects to the host on disconnect with exponential
  backoff (1 s → 30 s).
- Active-tab state is mirrored to `browser.storage.session` so suspend
  cycles don't drop the active tab.
