# panopticon

Local desktop-behaviour capture. Producers emit normalized JSONL
events; consumers (e.g. SATAN) read for aggregation, search, and
reflection.

## Components

- `panopticon-sway` — Sway IPC watcher daemon. Writes raw
  focus/window events to `~/.local/state/behaviour/raw/sway-YYYY-MM-DD.jsonl`.
- `panopticon-firefox-host` — Native messaging host for the Firefox
  WebExtension in `firefox-extension/`. Writes raw browser attention
  events to `~/.local/state/behaviour/raw/firefox-YYYY-MM-DD.jsonl`.
  See `firefox-extension/README.md` to install.
- `panopticon-segmentize` — Nightly batch. Derives `focus_segment` and
  `browser_tab_segment` events, computes daily histograms (per-app,
  per-workspace, per-domain, per-hour), enforces retention policy.

Planned producers: ghostty/zsh shell hook, emacs producer, idle/lock
watcher.

## Storage

```
~/.local/state/behaviour/
  raw/                 per-producer per-day JSONL; default retain 7 days
  segments/            derived focus intervals; default retain 90 days
  histograms/          daily aggregates; retained forever
  current/             last-known state per producer (atomic-replaced)
```

Append-only JSONL. POSIX `O_APPEND` writes are line-atomic up to
`PIPE_BUF` (4 KiB on Linux), so multiple producers may write
concurrently without coordination. See `docs/schema.md` for the wire
format and `docs/privacy.md` for what is and isn't captured.

## Status

- `panopticon-sway` watcher complete: lint clean, unit-tested for
  reconnect / backoff / per-day rotation / atomic current-state
  snapshot.
- `panopticon-segmentize` complete: per-source segment derivation
  (sway → `focus_segment`, firefox → `browser_tab_segment`), merged
  daily histograms, per-tier TTL retention.
- `panopticon-firefox-host` + `firefox-extension/` initial cut:
  protocol/validation/install paths unit-tested; extension load via
  `about:debugging` documented in `firefox-extension/README.md`.
  Manual smoke (real Firefox, real Sway join) still pending.
- Systemd unit files in `systemd/` are reference text; final wiring
  lives in `~/flakes/modules/home/behaviour.nix`.

## Manual smoke

```sh
# Inside a graphical-session.target sway:
nix run .#panopticon -- panopticon-sway -vv

# In another terminal:
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl
cat ~/.local/state/behaviour/current/sway.json | jq
```

## Development

```sh
# local venv (optional)
uv venv && uv pip install -e ".[dev]"

# tests
pytest

# nix build
nix build .#panopticon
```
