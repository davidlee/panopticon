# SPEC-001 recon notes (derived — regenerable reference)

Distilled from four read-only recon passes (watcher internals, schema/store/
segmentizer, consumers/packaging/docs, niri-ipc protocol). Not authored spec
content — a coupling map + proposed slice sequence to let a fresh agent resume
without re-running the recon. Decisions are locked in `spec-001.md` (D1–D7).

## Coupling map (file:line)

**Runner / adapter boundary**
- `panopticon/sway_watcher/runner.py:40-45` — `AsyncSession` protocol; `get_tree()`
  is the one true Sway leak. `:48-52` `AsyncSwayClient.session()`.
- `runner.py:86-121` `run_watcher` reconnect/backoff loop (generic already);
  `:72-73,:80-81` snapshot/current/event persistence; `:68-69` get_tree reconcile.
- `panopticon/sway_watcher/ipc.py:45-57,:94-138` — DEAD duplicate reconnect
  (`stream()`, `Ipc*`, `StreamMessage`); only `Backoff`(:60-88)+`IpcEvent` are live.
  Retire (D6).

**Sway-private logic to relocate**
- `state.py:19-38` `FocusState` (con_id,app_id,pid,title,workspace,output).
- `state.py:41-51` `app_id_from_container` (XWayland class/instance fallback).
- `state.py:54-66` `find_focused`; `:69-78` `ancestor_name_of_type`;
  `:81-98` `focus_state_from_tree` (derives workspace/output correctly via ancestry).
- `events.py:33-43` `transform` (handles only IPC kind window/workspace).
- `events.py:73-85` `_on_window_focus` — **THE BUG (D5)**: `:81-82` copies
  workspace/output from prev state, not the focused window.
- `_i3ipc.py` — only module importing `i3ipc`; queue-bridge adapter.

**"sway" literals (schema-keyed)**
- `events.py` `make_event("sway",…)` at 84,110,136,173,186,194,199,203.
- event NAMES `sway_disconnected`/`sway_reconnected` (events.py:197-203) — normalize
  to `compositor_disconnected`/`compositor_reconnected`.
- `sway_watcher/__main__.py:37` `--source` default "sway".

**Store (already source-parameterized)**
- `store.py:40-41` `raw/{source}-{day}.jsonl`; `:44-45` `current/{source}.json`;
  `:56-67` atomic write_current; `:47-54` day rotation; PIPE_BUF 4KiB assumption.

**Segmentizer registries (add "desktop")**
- `segmentizer/__main__.py:36-39` `_SOURCES = (("sway","focus",derive),("firefox",
  "browser",…))`; `:60` globs `raw/{prefix}-*.jsonl`.
- `segmentizer/retention.py:26-29` `_SEGMENT_PREFIX_FOR_RAW={"sway":"focus",
  "firefox":"browser"}`; `:93-98` `_source_from_raw_name`; `:101-109` match.
- `segmentizer/derive.py:35` `derive_segments(source="sway")`; `:6` STALE docstring
  (says sway-*, actual focus-*).
- Focus deriver keys on `(app_id, workspace)` — never source/con_id. `con_id` has
  ZERO consumers (H3).

**Schema (already producer-agnostic)**
- `schema.py:33-50` `Event{v,ts,source,event,fields}`; `:56-69` from_dict validation
  (no source/event value checks). `window_id` today is firefox-only
  (`segmentizer/browser.py:46,115,146`). No `producer` field anywhere.

**Packaging / services / docs**
- `pyproject.toml:21` `panopticon-sway = panopticon.sway_watcher.__main__:main`.
- `flake.nix:41` `meta.mainProgram="panopticon-sway"` — MUST move with rename or
  `nix run` breaks (HANDOVER.md:155-157). version drift: pyproject 0.1.0 vs flake 0.2.1.
- `systemd/sway-watcher.service:8` ExecStart=panopticon-sway. REAL units out-of-repo
  in `~/flakes/modules/home/nixos/behaviour.nix`.
- `docs/privacy.md:5` heading "## Sway watcher" (policy must persist verbatim).
- `README.md:13-54` arch diagram/table; `docs/schema.md:21,27-43` source "sway",
  partially stale event list (omits window_fullscreen_mode/window_urgent; lists
  unimplemented binding/mode/output/input).
- SATAN reads `segments/`+`histograms/` (already neutral) + `source` field +
  maybe `current/sway.json`. git_poller↔SATAN byte-contract is SEPARATE, untouched.

**Tests coupled to sway**
- `tests/fixtures/sway_events.jsonl` (source:sway, con_id:991).
- `tests/test_sway_{events,state,ipc,runner,main}.py`; `test_store.py`(sway-*.jsonl,
  sway.json); `test_schema.py`(sway sample); `test_segmentizer_*`.

## Niri protocol (v26.4.0 — pin before projection, OQ-3)

- `$NIRI_SOCKET`, AF_UNIX/SOCK_STREAM, NDJSON one-json-per-line.
- Send `"EventStream"` → reply `{"Ok":"Handled"}` → continuous `Event` lines to EOF.
- Initial burst: `WindowsChanged{windows}`, `WorkspacesChanged{workspaces}`,
  `WindowFocusChanged{id:Option<u64>}` then live deltas.
- Deltas: `WindowOpenedOrChanged{window}` (open OR mutate; novelty=id unseen),
  `WindowClosed{id}`, `WindowFocusChanged{id}` (single global focus),
  `WorkspaceActivated{id,focused}`, `WorkspaceActiveWindowChanged`,
  `Window/WorkspaceUrgencyChanged`. IDs u64, stable per lifetime, reusable after close.
- Window: app_id/title/pid all Option; `workspace_id:Option<u64>`; NO output field —
  derive via workspace. Workspace: `output:Option<String>`, `is_active`, `is_focused`,
  `active_window_id`. Build `active_workspace_by_output` from is_active+output.
- Unknown fields/variants guaranteed additive → ignore-and-continue, never crash.
- Refs: github.com/YaLTeR/niri/wiki/IPC ; niri-wm.github.io/niri/niri_ipc/enum.Event.html

## Proposed slice sequence (dependency order — not yet cut)

Revised from the brief's 7 given repo evidence (shared runner is thin; con_id is a
non-issue in-repo; segments already neutral):

1. **SL — Shared model + runner extraction.** Introduce `compositor/model.py`
   (WindowRef/DesktopState/DesktopObservation, CompositorSession/Client protocols),
   `compositor/runner.py` (move generic loop), `compositor/events.py` (neutral
   encoder). Retire dead `ipc.py` reconnect (D6). Sway still the only adapter, wired
   through the new contract. Behaviour-preserving: existing sway fixtures green.
2. **SL — Move Sway behind the adapter.** Relocate state.py/events.py/_i3ipc.py into
   `compositor/sway/`. Implement CompositorSession. **Fix D5 focus bug** here +
   update fixtures with documented behaviour-change note. Golden/equivalence tests.
3. **SL — Schema migration (D1) + compat (D2).** `source:"desktop"`+`producer`,
   `window_id` (dual-emit con_id), `current/desktop.json` (+ side-write sway.json),
   `raw/desktop-*.jsonl`. Add "desktop" to `_SOURCES`/`_SEGMENT_PREFIX_FOR_RAW`/
   retention parse. Update segmentizer + tests.
4. **SL — Shared CLI + detection (D7).** `panopticon-desktop --compositor
   auto|sway|niri`, `compositor/detect.py`, keep `panopticon-sway` wrapper, move
   `nix meta.mainProgram`. `desktop_watcher/__main__.py`.
5. **SL — Niri protocol + projection (D3).** `compositor/niri/{protocol,projection}.py`,
   socket framing, initial-state accumulation, projection transitions. Recorded-
   fixture tests. Pin niri-ipc v26.4.0 first (OQ-3).
6. **SL — Niri normalization.** Emit normalized snapshot + observations; focus/title/
   workspace/output correctness; reconnect + EOF tests; cross-compositor equivalence.
7. **SL — Docs + operational migration.** README/schema.md/privacy.md heading;
   systemd/HM units (OQ-2); Sway↔Niri switching; drop D2 compat once OQ-1 verified.

## Decision status
- D1–D7 locked (spec-001.md). OQ-1 (out-of-repo con_id/current readers), OQ-2
  (unit rename), OQ-3 (pin niri-ipc shapes) OPEN — resolve at the noted slices.

## Next action for resuming agent
1. Adversarial review of SPEC-001 (design skill rhythm — second agent or, with user
   OK, codex/gpt-5.5). Then flip status draft→ (whatever the accepted state is).
2. Cut slice family: `doctrine slice new` ×7 with `needs`/`after` edges per sequence
   above, `descends_from`/`parent` → SPEC-001. Then design+plan SL-1 just-in-time.
3. Consider whether a product spec (PRD) is warranted, or the brief suffices as the
   "why". User chose "tech spec first" — product spec was skipped deliberately.
