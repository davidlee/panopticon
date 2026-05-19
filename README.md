# panopticon

Local desktop-behaviour capture. Producers emit normalized JSONL
events; consumers (e.g. SATAN) read for aggregation, search, and
reflection.

## Components

- `panopticon-sway` — Sway IPC watcher daemon. Writes raw
  focus/window events to `~/.local/state/behaviour/raw/sway-YYYY-MM-DD.jsonl`.
- `panopticon-segmentize` — Nightly batch. Derives focus segments,
  computes daily histograms, enforces retention policy.

Planned producers: firefox extension + native host, ghostty/zsh shell
hook, emacs producer, idle/lock watcher.

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

- `panopticon-sway` watcher complete: 76 unit tests, lint clean. Manual
  smoke against a running compositor still pending. Reconnect /
  backoff / per-day rotation / atomic current-state snapshot all
  exercised in tests.
- `panopticon-segmentize` segmentizer: stub only — derivation,
  histograms, and retention land next.
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
