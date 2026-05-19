# panopticon — handover

Read `README.md` first, then this. Caveman OK; technical substance below.

## Status (2026-05-19)

**v0.1 sway watcher + segmentizer** built end-to-end and smoke-confirmed
against a live compositor. Daemon runs via `nix run .#panopticon -- -vv`,
writes to `~/.local/state/behaviour/{raw,current}/`. Nightly
`panopticon-segmentize` derives `segments/focus-<day>.jsonl`,
`histograms/daily-<day>.json`, and enforces per-tier retention. 105 unit
tests + ruff clean. Manual smoke verified: 1110 raw events on real
activity → 75 focus_segments, plausible per-app totals.

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
| `panopticon/segmentizer/derive.py` | `derive_segments` — pure raw-event → `focus_segment` collapser |
| `panopticon/segmentizer/histogram.py` | `aggregate` — per-app / per-workspace / per-hour day totals |
| `panopticon/segmentizer/retention.py` | `enforce` — 7d raw (only if segmented) / 90d segments / ∞ histograms |
| `panopticon/segmentizer/__main__.py` | `run(root, today=)` + argparse for `panopticon-segmentize` |

Two protocols (`AsyncSession`, `AsyncSwayClient`) form the testability
boundary. The runner never imports `i3ipc`; adapter swap (wlroots, kde,
fake) is one new module.

## Storage tiers

```
~/.local/state/behaviour/
  raw/sway-YYYY-MM-DD.jsonl    per-source per-day; retain 7d (only if segmented)
  current/sway.json             last known focused state (atomic-replace)
  segments/focus-YYYY-MM-DD.jsonl  derived; retain 90d
  histograms/daily-YYYY-MM-DD.json  per-day aggregates; retain ∞
```

## Pending work (priority order)

1. **SATAN consumer** (lives in `~/.emacs.d/satan/`, not this repo):
   `activity_read` tool that reads
   `~/.local/state/behaviour/{segments,histograms}/` (raw as fallback)
   and returns aggregated text to the LLM. Tracked separately in
   `~/.emacs.d/` SATAN tasks.

2. **Flake input stability**: `~/flakes/flake.nix` uses
   `panopticon.url = "path:/home/david/dev/panopticon"`. Switch to
   `git+file:///home/david/dev/panopticon` (or a real remote) once the
   churn slows so home-manager evaluates against a clean tree instead
   of the dirty working copy.

3. **Open design questions** worth revisiting once data accumulates:
   - Idle detection — long unbroken segments overstate active focus.
     Could split when no input events arrive for N minutes (needs a
     secondary signal — `swayidle` or libinput).
   - Title-change segmentation — currently grouped only by
     `(app_id, workspace)`. Browser tabs / editor buffers may warrant
     a finer cut once we know what consumers want.
   - Segments-file naming: currently `focus-<day>.jsonl` (single
     event-type). If we add another segment type (e.g. browser tabs)
     we may want `<source>-<day>.jsonl` like raw/. Retention already
     keys off the trailing `-YYYY-MM-DD.jsonl` suffix so renaming is
     cheap.

## Smoke recipe

```sh
cd ~/dev/panopticon
nix run .#panopticon -- -vv             # watcher in terminal A
# in terminal B:
ls -la ~/.local/state/behaviour/raw/
jq < ~/.local/state/behaviour/current/sway.json
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl

# segmentizer (one-shot)
uv run --extra dev python -m panopticon.segmentizer -vv
jq '.per_app_seconds' ~/.local/state/behaviour/histograms/daily-$(date +%Y-%m-%d).json
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

## Flake integration

Home-manager module lives in `~/flakes/modules/home/nixos/behaviour.nix`
(this repo only ships the package + systemd unit text). It declares:

- `panopticon-sway.service` (simple, `Restart=always`, bound to
  `graphical-session.target`)
- `panopticon-segmentize.service` (`Type=oneshot`)
- `panopticon-segmentize.timer` (`OnCalendar=*-*-* 03:30:00`,
  `Persistent=true`, `RandomizedDelaySec=15min`)

Flake input is `path:/home/david/dev/panopticon` (dirty-tree
warning is expected during local iteration). Activation:
`home-manager switch --flake ~/flakes#david`.

## Commit log

```
75502e0 feat(segmentizer): wire panopticon-segmentize entrypoint
5ed8174 feat(segmentizer/retention): per-tier TTL
44d8ed7 feat(segmentizer/histogram): per-day aggregates
8318733 feat(segmentizer/derive): focus events → focus_segment
09b2030 docs: HANDOVER.md for the next agent
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
