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
- (future) `firefox`, `ghostty`, `emacs`, `idle`.

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
