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

- `sway` — compositor events from the Sway IPC watcher.
- `firefox` — active-tab attention events from the Firefox WebExtension
  via `panopticon-firefox-host`.
- (future) `ghostty`, `emacs`, `idle`.

## Sway events

Stubs — implementation pending. Expected event names:

- `window_focus`
- `window_title`
- `window_new`
- `window_close`
- `window_move`
- `workspace_focus`
- `workspace_urgent`
- `binding`
- `mode`
- `output`
- `input`
- `sway_disconnected`
- `sway_reconnected`
- `snapshot` (emitted on init / reconnect)

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

- `focus_segment` (`focus-*.jsonl`) — contiguous `(app_id, workspace)`
  interval. Source `sway`.
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
