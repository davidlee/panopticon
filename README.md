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
  raw/sway-YYYY-MM-DD.jsonl        compositor events; retain 7 days (only once segmented)
  raw/firefox-YYYY-MM-DD.jsonl     browser events;    retain 7 days (only once segmented)
  segments/focus-YYYY-MM-DD.jsonl  derived from sway;    retain 90 days
  segments/browser-YYYY-MM-DD.jsonl  derived from firefox; retain 90 days
  histograms/daily-YYYY-MM-DD.json   per-day aggregates (focus + browser merged); retained forever
  current/sway.json                  last-known sway state (atomic-replaced)
```

Append-only JSONL. POSIX `O_APPEND` writes are line-atomic up to
`PIPE_BUF` (4 KiB on Linux), so multiple producers may write
concurrently without coordination. Retention is source-aware: a raw
file is deleted only once its matching segment file exists, so a
missed segmentizer run cannot lose data. See `docs/schema.md` for the
wire format and `docs/privacy.md` for what is and isn't captured.

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

### Sway watcher

```sh
# Inside a graphical-session.target sway:
nix run .#panopticon -- panopticon-sway -vv

# In another terminal:
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl
cat ~/.local/state/behaviour/current/sway.json | jq
```

### Firefox extension

```sh
# Install the native messaging host manifest:
uv pip install -e .
panopticon-firefox-host install-manifest

# Load the extension in Firefox:
#   about:debugging#/runtime/this-firefox
#   → "Load Temporary Add-on…"
#   → pick firefox-extension/manifest.json

tail -f ~/.local/state/behaviour/raw/firefox-$(date +%Y-%m-%d).jsonl
```

URLs are stripped of query strings and fragments before they leave the
extension and again at the host; incognito tabs and sensitive schemes
(`about:`, `moz-extension:`, `data:`, etc.) are dropped at both ends.
See `firefox-extension/README.md` for the full install + test
procedure and `browser.local.md` for the design.

### Segmentizer

```sh
uv run panopticon-segmentize -v
jq '.per_app_seconds, .per_domain_seconds' \
  ~/.local/state/behaviour/histograms/daily-$(date +%Y-%m-%d).json
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

### Propagating changes to the running daemon

The user systemd units (`panopticon-sway`, `panopticon-segmentize`) are
wired up by home-manager via `~/flakes/modules/home/nixos/behaviour.nix`,
which pulls panopticon in as a `path:/home/david/dev/panopticon` flake
input. That input is locked by narHash, so source edits in this repo do
**not** reach systemd until the lock is bumped and home-manager is
re-activated. `nix build .#panopticon` updates `./result` but does
nothing to the unit's `ExecStart`, which stays pinned to the previous
`/nix/store/...-panopticon-0.1.0/bin/...` path.

Helper script — runs the full cycle:

```sh
./bin/reload-hm
```

It does:

1. `nix flake update panopticon` in `~/flakes` (re-locks to current HEAD
   of this working tree).
2. `home-manager switch --flake ~/flakes#david` (rebuilds the user
   environment, relinks the systemd units to the new store path).
3. `systemctl --user reset-failed panopticon-segmentize.service` (clears
   any prior failure so the next timer fires cleanly).

Override the flakes dir / HM target with `PANOPTICON_FLAKES_DIR` and
`PANOPTICON_HM_TARGET` env vars.

If you skip this, symptom is: code change visible in the repo, tests
pass, `nix build` succeeds, but `systemctl --user status
panopticon-segmentize` still references the old store hash and runs old
behaviour (or worse, an old `NotImplementedError` stub).
