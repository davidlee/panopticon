# panopticon — handover

Read `README.md` first, then this. Caveman OK; technical substance below.

## Status (2026-05-19)

**v0.1 sway watcher + segmentizer + firefox capture** built end-to-end
and smoke-confirmed. Daemon runs via `nix run .#panopticon -- -vv`,
writes to `~/.local/state/behaviour/{raw,current}/`. Nightly
`panopticon-segmentize` derives `segments/focus-<day>.jsonl` (sway) and
`segments/browser-<day>.jsonl` (firefox), merges per-app + per-domain
into `histograms/daily-<day>.json`, and enforces per-tier retention
(source-aware: firefox raw retained until matching browser segment
exists).

171 unit tests + ruff clean. Sway smoke previously verified: 1110 raw
events → 75 focus_segments, plausible per-app totals. Firefox smoke
verified: extension loaded via `about:debugging`, events streaming to
`raw/firefox-<day>.jsonl` (browser_window_focus, browser_tab_active,
browser_tab_updated, browser_navigation) with query/fragment stripped
and incognito tabs dropped at source.

## Architecture

```
sway IPC      ─► I3ipcSwayClient   ─► runner.process_session ─► RawStore ─► raw/sway-*.jsonl
                                                                       ─► current/sway.json

Firefox WebExt ─► native-msg port  ─► firefox_host.run_loop  ─► RawStore ─► raw/firefox-*.jsonl
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
| `panopticon/firefox_host/protocol.py` | 4-byte LE length-prefix native-messaging framing |
| `panopticon/firefox_host/validate.py` | pure validate + redact (strip query/fragment, drop sensitive schemes, drop incognito, re-stamp source) |
| `panopticon/firefox_host/install.py` | render + write `~/.mozilla/native-messaging-hosts/panopticon_firefox.json` |
| `panopticon/firefox_host/__main__.py` | `run_loop(stdin, store)` + `install-manifest` subcommand; tolerates Firefox's `[manifest_path, ext_id]` argv |
| `firefox-extension/manifest.json` | MV3 manifest; perms `tabs, webNavigation, idle, nativeMessaging, storage`; `data_collection_permissions=[browsingActivity]` |
| `firefox-extension/background.js` | listeners for tabs/webNavigation/windows/idle; URL redaction + incognito drop; reconnect with backoff |
| `panopticon/segmentizer/derive.py` | `derive_segments` — pure raw-event → `focus_segment` collapser |
| `panopticon/segmentizer/browser.py` | `derive_browser_segments` — firefox raw → `browser_tab_segment` |
| `panopticon/segmentizer/histogram.py` | `aggregate` (focus) + `aggregate_browser` (per-domain); merged into one daily file |
| `panopticon/segmentizer/retention.py` | `enforce` — 7d raw (only if matching-source segment exists) / 90d segments / ∞ histograms |
| `panopticon/segmentizer/__main__.py` | `run(root, today=)` driven by `_SOURCES` table — add producer in one line |

Two protocols (`AsyncSession`, `AsyncSwayClient`) form the testability
boundary. The runner never imports `i3ipc`; adapter swap (wlroots, kde,
fake) is one new module.

## Storage tiers

```
~/.local/state/behaviour/
  raw/sway-YYYY-MM-DD.jsonl        per-source per-day; retain 7d (only if matching segment exists)
  raw/firefox-YYYY-MM-DD.jsonl     "
  current/sway.json                last known focused state (atomic-replace)
  segments/focus-YYYY-MM-DD.jsonl  derived from sway raw; retain 90d
  segments/browser-YYYY-MM-DD.jsonl  derived from firefox raw; retain 90d
  histograms/daily-YYYY-MM-DD.json   per-day aggregates (focus + browser merged); retain ∞
```

Retention is source-aware: `sway-<day>.jsonl` requires `focus-<day>.jsonl`
before deletion; `firefox-<day>.jsonl` requires `browser-<day>.jsonl`.
Mapping lives in `segmentizer/retention.py:_SEGMENT_PREFIX_FOR_RAW`;
mirror it when adding sources.

**Day bucketing is on the stamped offset.** `RawStore.write` files an
event by `event.ts[:10]` — the day *as the producer wrote it*. So every
producer must stamp **local time with offset** (`+10:00`), not UTC `Z`;
otherwise its raw files bucket on UTC midnight, splitting a local day
across two files and tripping `sleipnir-doctor-panopticon` every morning
until the offset rolls over. Sway stamps local via `schema.utc_now_iso`;
the firefox extension does too (`background.js:nowIso`, fixed in 0.1.1 —
it previously emitted `Z`). The doctor now checks both the local- and
UTC-dated file as a backstop for any future producer that regresses.

## Pending work (priority order)

1. **Firefox + Sway join layer**. Per `browser.local.md`,
   `browser_tab_segment` should be discounted when the overlapping
   `focus_segment` is not Firefox. Stub TODO in
   `panopticon/segmentizer/browser.py`. Likely a new module
   `segmentizer/join.py` that emits a filtered `attention_segment`
   stream alongside the raw browser segments.

2. **Firefox extension packaging** — *resolved (0.1.1)*. Signed via AMO;
   `just package-extension` builds `panopticon.zip` (manifest at archive
   root) for upload. Each upload needs a fresh `manifest.json` version
   bump — AMO rejects duplicates. `web-ext` is in the devShell for
   `web-ext sign --api-key` if scripting it later.

3. **SATAN consumer** (lives in `~/.emacs.d/satan/`, not this repo):
   `activity_read` tool that reads
   `~/.local/state/behaviour/{segments,histograms}/` (raw as fallback)
   and returns aggregated text to the LLM. Tracked separately in
   `~/.emacs.d/` SATAN tasks.

4. **Flake input stability**: `~/flakes/flake.nix` uses
   `panopticon.url = "path:/home/david/dev/panopticon"`. Switch to
   `git+file:///home/david/dev/panopticon` (or a real remote) once the
   churn slows so home-manager evaluates against a clean tree instead
   of the dirty working copy.

5. **Open design questions** worth revisiting once data accumulates:
   - Idle detection across sources — sway watcher has none; firefox
     idle is reported but never enriches sway segments. Could surface
     a unified `idle_segment` stream from a swayidle/libinput watcher.
   - Title-change segmentation — sway focus segments currently grouped
     only by `(app_id, workspace)`. Browser tabs are now segmented
     finely (per URL); editor buffers may warrant similar treatment.
   - Content-script signals (visibility, scroll, audible) for the
     Firefox extension — deliberately deferred for v1.
   - Per-source histogram keys may collide on `day`; merging works for
     now because both aggregators emit the same `day` value, but
     adding a third source should formalize the schema.

## Smoke recipe

```sh
cd ~/dev/panopticon
nix run .#panopticon -- -vv             # sway watcher in terminal A
# in terminal B:
ls -la ~/.local/state/behaviour/raw/
jq < ~/.local/state/behaviour/current/sway.json
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl

# firefox extension (one-time setup)
uv pip install -e .
panopticon-firefox-host install-manifest
# in Firefox: about:debugging → Load Temporary Add-on → firefox-extension/manifest.json
tail -f ~/.local/state/behaviour/raw/firefox-$(date +%Y-%m-%d).jsonl

# segmentizer (one-shot)
uv run --extra dev python -m panopticon.segmentizer -vv
jq '.per_app_seconds, .per_domain_seconds' \
  ~/.local/state/behaviour/histograms/daily-$(date +%Y-%m-%d).json
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
- **Firefox passes positional argv to native hosts**: when launched,
  argv is `[manifest_path, extension_id]`. argparse subcommand-based
  parsers reject them → host SystemExits → port disconnects → extension
  reconnect loop. Fix: `parse_known_args` and discard positionals when
  no subcommand prefix matches.
- **MV3 background script `"type": "module"`**: defers listener
  registration past initial load → first events silently dropped.
  Removed `type: "module"` from the manifest; we have no imports
  anyway.
- **Firefox 138+ requires `data_collection_permissions`**: declared
  `["browsingActivity"]` in `browser_specific_settings.gecko`. Without
  it the extension may silently fail to surface URLs.
- **Native host name underscores only**: `panopticon_firefox` (Firefox
  rejects hyphens in native messaging host names).

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
1536ecd docs: firefox capture pipeline
4aa9fca feat(firefox-extension): MV3 active-tab capture
5a94c48 feat(segmentizer/browser): derive browser_tab_segment + per-domain histogram
f8026c3 feat(firefox-host): native messaging bridge
e15ca18 docs: refresh HANDOVER.md post-segmentizer
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
