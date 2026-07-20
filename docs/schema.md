# panopticon event schema

**Schema version:** 1.

Each event is one JSON object on one line of a `.jsonl` file:

```json
{
  "v": 1,
  "ts": "<ISO 8601 with timezone offset>",
  "source": "<producer name>",
  "event": "<event name>",
  ...event-specific fields...
}
```

Consumers must skip lines whose `v` they don't understand.

## Sources

- `desktop` — compositor events from the neutral desktop watcher
  (`panopticon-desktop`). Every event also carries a `producer` field naming
  the live compositor — `sway` or `niri`. Running either compositor writes
  `source:"desktop"` (`raw/desktop-*.jsonl`).
- `firefox` — active-tab attention events from the Firefox WebExtension
  via `panopticon-firefox-host`.
- `sway` — **retired historical source.** Pre-migration builds wrote
  `source:"sway"` / `raw/sway-*.jsonl`; running Sway now writes `desktop`
  (with `producer:"sway"`). Existing `sway` raws are frozen and age out of
  the retention window; no new ones are produced.
- (future) `ghostty`, `emacs`, `idle`.

## Desktop events

Emitted by the neutral watcher (`panopticon-desktop`) over either compositor
adapter. Every event carries `source:"desktop"` plus a `producer` (`sway` or
`niri`) and, where a window is involved, `window_id`, `app_id`, `pid`, `title`,
`workspace`, and `output` (null-valued keys are omitted).

Common to both adapters:

- `snapshot` — full focused-window state, emitted on init and after reconnect.
- `window_focus` — focused window changed.
- `window_title` — the focused window's title changed. Carries `old_title` and
  `title`.
- `workspace_focus` — active workspace changed. Carries `old_workspace`,
  `workspace`, and `output`.

Connection lifecycle (emitted by the watcher's reconnect loop):

- `compositor_disconnected` — the IPC connection dropped (carries a `reason`).
- `compositor_reconnected` — reconnected after a non-first connect (the session
  supplies a fresh `snapshot` immediately after).

The Sway adapter additionally passes through these i3ipc window/workspace change
events (the Niri adapter emits none of them):

- `window_new`
- `window_move`
- `window_fullscreen_mode`
- `window_urgent`
- `window_close`
- `workspace_urgent`

## Firefox events

Emitted by the Firefox WebExtension and re-stamped to `source="firefox"`
by `panopticon-firefox-host`. URLs are redacted to `scheme://host/path`
(query + fragment stripped); sensitive schemes are dropped at both the
extension and the host.

- `browser_snapshot` — extension startup; carries the current active
  tab.
- `browser_tab_active` — active tab changed.
- `browser_tab_updated` — title / status / audible changed on the
  active tab. Carries a `change` map indicating which fields moved.
- `browser_navigation` — real (`kind="committed"`) or SPA
  (`kind="history_state_updated"`) navigation in the main frame of the
  active tab.
- `browser_window_focus` — Firefox itself gained or lost focus.
- `browser_idle_state` — system idle state changed (`active`, `idle`,
  `locked`).

URL-bearing events include `url`, `domain`, `window_id`, `tab_id`,
`incognito: false`. Incognito events are dropped before they reach the
host.

## Segments

Derived by `panopticon-segmentize` and written to
`segments/<prefix>-YYYY-MM-DD.jsonl`.

- `focus_segment` (`focus-*.jsonl`) — contiguous focused-window interval.
  Source `desktop`. Its identity key is `(producer, output, app_id,
  workspace)` — `producer` and `output` keep same-named workspaces on
  different compositors/outputs from being conflated. Fields: `app_id`,
  `workspace`, `start_ts`, `end_ts`, `duration_s`, plus `producer` and
  `output` when present, and optional `last_title` — the most recent window
  title observed during the segment (from `window_focus`, `window_title`, or
  `snapshot` events). `last_title` is omitted when no title was observed;
  downstream consumers must treat absence as unknown. Legacy `sway` segments
  omit `producer`/`output` and stay byte-identical.
- `browser_tab_segment` (`browser-*.jsonl`) — contiguous in-browser
  attention on one URL. Fields: `start_ts`, `end_ts`, `duration_s`,
  `window_id`, `tab_id`, `url`, `domain`, `title_start`, `title_end`,
  `audible`. Source `firefox`.

## Histograms

`histograms/daily-YYYY-MM-DD.json` is a merged per-day aggregate:

```
{
  "day": "YYYY-MM-DD",
  "per_app_seconds":          {app_id: seconds, ...},
  "per_workspace_seconds":    {workspace: seconds, ...},
  "per_hour_seconds":         [s_0, ..., s_23],
  "per_domain_seconds":       {domain: seconds, ...},
  "per_browser_hour_seconds": [s_0, ..., s_23]
}
```

The `per_workspace_seconds` key is `"output/workspace"` when the segment
carries an `output` (niri — e.g. `"DP-1/3"`), disambiguating same-named
workspaces across monitors; legacy `sway` segments (no `output`) key on the
bare `workspace` name.
