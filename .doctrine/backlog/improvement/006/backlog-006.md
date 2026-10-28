# IMP-006: keyrate: typing rate per window (app, title), attributed at capture

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-10-28 from a SATAN conversation: "minutes typing in emacs" needs
key counts per focused window, not system-wide. The "later, optional" step of
IMP-005. Consumer: SATAN's `activity_read` MCP tool (its `today` scope returns
the daily histogram verbatim, so a new histogram key reaches it with no SATAN
change). Not the bar.

## Why at capture, not a segmentizer join

Measured on 2026-10-26/27: of minutes with keys, 32–43% overlap more than one
app and 77–78% more than one (app, title) — 60% of keys. A minute row cannot
be split after the fact.

## Design

```
evdev ──▶ Counter.record(activity, t, window) ──┐
current/desktop.json ─▶ FocusReader (stat mtime,│
                         re-read on change)     ▼
                       raw/keyrate-*: keyrate_minute (unchanged)
                                    + keyrate_window per (minute, app_id, title)
                                          │
                        segmentizer ──────▼
                       histograms/daily-*: typing_per_app
                         {app: {keys, key_seconds, wpm, titles: {title: {…}}}}
```

- **`keyrate_minute` is unchanged**: SATAN's presence reader sums it. Window
  rows are a separate event; their `key_seconds` do not sum to the minute's
  (a second can hold keys in two windows).
- **Focus source**: `current/desktop.json`, the desktop watcher's published
  current state. A file contract, not a code dependency. Missing file or null
  `app_id` → the key is unattributed (counted in the minute row only). A dead
  watcher leaves a stale file: keys go to the last focused window.
- **Title normalisation** (pure, at capture so buckets merge): strip a leading
  run of Unicode symbol characters (category `So`: braille spinners `⠋`,
  `◐◑`, `✳`) and whitespace. Applied to every app; costs a leading emoji.
- **wpm** = `keys / 5` per minute of `key_seconds` — the rate while typing,
  not over focus time.
- **Privacy**: per-minute counts only, as IMP-005. New: per-minute key counts
  per title. A shell that titles each command lets the count approximate the
  command's length; the title already says more.

## Open

- Raw keyrate is kept indefinitely (IMP-005); it now carries titles. Desktop
  raw is kept 7 days. Retention for keyrate raw should follow once the
  histogram exists for the day.

## Landed (2026-10-28)

- `Counter.record(activity, t, window)`; `MinuteRow.windows`
  (`panopticon/keyrate/count.py`).
- `window_of` + title de-spinnering, pure (`panopticon/keyrate/focus.py`).
- `keyrate_window` events (`render.window_events`); `CurrentWindow` reader in
  the shell, one `stat` per key press, re-read on inode/mtime change.
- `aggregate_typing` → histogram `typing_per_app`
  (`panopticon/segmentizer/histogram.py`); the segmentizer reads
  `raw/keyrate-<day>.jsonl` for each day it rebuilds.
- Docs: `schema.md`, `privacy.md`, README.

Remaining: deploy (bump panopticon in `~/flakes`, restart
`panopticon-keyrate`); windows appear from that point, no backfill. Retention
question above still open.
