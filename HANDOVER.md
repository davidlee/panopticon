# panopticon — handover

Read `README.md` first, then this. Caveman OK; technical substance below.

## Status (2026-05-19)

**v0.1 sway watcher** built end-to-end and smoke-confirmed against a
live compositor. Daemon runs via `nix run .#panopticon -- -vv`, writes
to `~/.local/state/behaviour/{raw,current}/`, 76 unit tests + ruff
clean. Manual smoke verified: focus / title / workspace events flow
to JSONL on real activity.

## Architecture

```
sway IPC ─► I3ipcSwayClient ─► runner.process_session ─► RawStore ─► raw/*.jsonl
                                                                ─► current/*.json
```

Modules (each tested in isolation, pure where possible):

| file | role |
|---|---|
| `panopticon/schema.py` | `Event` dataclass (v=1); JSONL round-trip; `iter_jsonl` |
| `panopticon/store.py` | `RawStore` — per-day rotation, atomic `current/` snapshot, POSIX O_APPEND |
| `panopticon/sway_watcher/state.py` | `FocusState` + `get_tree`-walking helpers |
| `panopticon/sway_watcher/events.py` | IPC payload → `Event` + next state |
| `panopticon/sway_watcher/ipc.py` | `Backoff`, `IpcEvent` / `IpcDisconnected` / `IpcReconnected`, generic `stream()` |
| `panopticon/sway_watcher/runner.py` | `process_session` + `run_watcher`; `AsyncSession` / `AsyncSwayClient` protocols |
| `panopticon/sway_watcher/_i3ipc.py` | i3ipc-python adapter — only place that imports `i3ipc` |
| `panopticon/sway_watcher/__main__.py` | argparse + `asyncio.run` + signal handlers |

Two protocols (`AsyncSession`, `AsyncSwayClient`) form the testability
boundary. The runner never imports `i3ipc`; adapter swap (wlroots, kde,
fake) is one new module.

## Storage tiers

```
~/.local/state/behaviour/
  raw/sway-YYYY-MM-DD.jsonl    per-source per-day; default retain 7d (NOT YET ENFORCED)
  current/sway.json             last known focused state (atomic-replace)
  segments/focus-YYYY-MM-DD.jsonl  derived; retain 90d (NOT YET BUILT)
  histograms/daily-YYYY-MM-DD.json  per-day aggregates; retain ∞ (NOT YET BUILT)
```

## Pending work (priority order)

1. **`~/flakes/modules/home/behaviour.nix`** — wire panopticon as flake
   input (start with `path:/home/david/dev/panopticon`, switch to
   `git+file://` once stable). Add systemd user unit
   `panopticon-sway.{service}` with `Type=simple`, `Restart=always`,
   `After=graphical-session.target`. Reference unit text already in
   `systemd/sway-watcher.service`. User triggers
   `home-manager switch --flake ~/flakes#david`.

2. **Segmentizer** (`panopticon-segmentize` is a stub that raises
   NotImplementedError):
   - `segmentizer/derive.py` — collapse contiguous focus events on
     same `(app_id, workspace)` into `focus_segment` events
   - `segmentizer/histogram.py` — per-day aggregates: per-app
     seconds, per-workspace seconds, per-hour distribution
   - `segmentizer/retention.py` — enforce per-tier TTL with
     atomic-rename writes; never delete unsegmented raw
   - `segmentizer/__main__.py` — wire as `oneshot` + daily timer
     (template in `systemd/segmentizer.{service,timer}`)

3. **SATAN consumer** (lives in `~/.emacs.d/satan/`, not this repo):
   `activity_read` tool that reads `~/.local/state/behaviour/raw/`
   and returns aggregated text to the LLM. Tracked separately in
   `~/.emacs.d/` SATAN tasks.

## Smoke recipe

```sh
cd ~/dev/panopticon
nix run .#panopticon -- -vv             # daemon in terminal A
# in terminal B:
ls -la ~/.local/state/behaviour/raw/
jq < ~/.local/state/behaviour/current/sway.json
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl
```

## Gotchas debugged this session

- **`pytest-asyncio` in `nativeCheckInputs`**: `pytestCheckHook` ships
  only pytest. Local `uv run` works (resolves dev extras); nix build
  doesn't. Lesson: every `[dev]` dep used at test time needs an explicit
  Nix mirror.
- **`meta.mainProgram` required**: package produces `panopticon-sway`
  and `panopticon-segmentize`, not `panopticon`. Without
  `meta.mainProgram = "panopticon-sway"`, `nix run .#panopticon` errors
  with "No such file or directory" for `bin/panopticon`.
- **`i3ipc` upstream `SyntaxWarning`**: `break` in `finally` block at
  `i3ipc/connection.py:508` and `:511`. Harmless. Not ours to fix.
- **Silent watcher ≠ broken watcher**: the runner had no log calls
  on the hot path, so DEBUG/INFO terminal output was empty even with
  events flowing to JSONL. Now logs each event at INFO; ground truth
  is the JSONL file.
- **`uv run` creates `.venv/`**: gitignored; don't accidentally commit.

## Conventions

- Conventional commits: `feat(<scope>): …`, `fix(<scope>): …`.
- Test-first; every public function gets a deterministic test.
- Pure functions in `schema`, `state`, `events`; protocols at IO
  boundaries (`runner.AsyncSession`/`AsyncSwayClient`).
- Schema versioning: bump `SCHEMA_VERSION` only on shape change, not
  for new `event` names within v=1.
- New producers: same `raw/` dir, different `source` (filename prefix).
  e.g. firefox-host → `raw/firefox-YYYY-MM-DD.jsonl`.

## Useful one-liners

```sh
uv run --extra dev pytest -q            # local tests (with venv)
uv run --extra dev ruff check .         # lint
nix build .#panopticon --no-link        # nix build with checkPhase
nix run .#panopticon -- -vv             # run watcher
```

## Commit log

```
7b3fcdc fix: debug output
8fc45bf fix(flake): set meta.mainProgram so nix run picks the watcher
daeee8a fix(flake): add pytest-asyncio to nativeCheckInputs
6ae150f feat(sway_watcher): i3ipc adapter + panopticon-sway entrypoint
b5276ba feat(sway_watcher/runner): process_session + run_watcher loop
de04b28 feat(sway_watcher/ipc): Backoff + reconnect-aware async stream
c636ba4 feat(sway_watcher/events): IPC payload → normalized Event + state
c1d827a feat(sway_watcher/state): FocusState + tree-walking snapshot
3ec530d feat(store): RawStore — per-day JSONL writer + atomic snapshot
80e85ca feat(schema): v1 Event dataclass + JSONL round-trip
9ba5579 init: scaffold panopticon v0.1.0
```
