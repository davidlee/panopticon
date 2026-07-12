# SPEC-001: Compositor-neutral desktop watcher

<!-- Reference forms: entity ids padded (SPEC-007, ADR-004); doc-local refs bare
     (D1 decision, OQ-1 open question). See .doctrine/glossary.md § reference forms. -->

## Overview

Panopticon captures local desktop-attention behaviour. Today one producer — the
Sway watcher — consumes Sway's i3ipc model directly and emits schema events with
`source: "sway"`. This spec defines a **compositor-neutral desktop watcher**: a
shared domain model, runner, and event encoder behind which Sway and **Niri** are
peer adapters. Each adapter connects to its native IPC, maintains whatever native
projection it needs, and normalizes to shared *desktop observations*. Nothing
above the adapter boundary knows about Sway trees, Niri event variants, container
ancestry, or socket framing.

C4 frame: this is the **container** that replaces `panopticon.sway_watcher`.
Internally it decomposes into a compositor-neutral core (`compositor/model`,
`compositor/runner`, `compositor/events`, `compositor/detect`), two adapter
components (`compositor/sway`, `compositor/niri`), and the `desktop_watcher`
entrypoint. Downstream (segmentizer, store, SATAN) is unchanged except for the
`source`/`producer`/`window_id` schema migration.

The boundary, top to bottom:

```
native compositor IPC  (i3ipc events / niri JSON socket)
        ↓  adapter-private decode + projection
compositor-specific adapter  (CompositorSession)
        ↓  normalized DesktopObservation / DesktopState
shared runner + event encoder
        ↓  schema.Event {source:"desktop", producer, event, window_id, …}
store  →  raw/desktop-DAY.jsonl · current/desktop.json
```

Raw native IPC events are **not** part of the shared API. Native-only capabilities
(Sway marks, Niri columns) live in adapter-private metadata or nowhere — never in
the shared model (see D4).

## Responsibilities

Mirrors the structured `responsibilities` list in `spec-001.toml`. In one line:
own the neutral model + runner + event encoding + adapter selection, and host the
two adapters that translate native IPC into normalized observations — while
preserving Sway behaviour and the existing privacy policy.

## Concerns

- **Behaviour preservation (Sway).** The extraction must keep existing Sway
  fixtures and consumers working. The one deliberate exception is the
  workspace/output focus bug (see D5) — an intentional, documented behaviour
  change, not silent drift.
- **Purity.** Native decode, projection transitions, observation construction, and
  event encoding must be pure and unit-testable without a live compositor. I/O,
  reconnect, and backoff live in the thin async shell (mostly the existing runner).
  Honours the project pure/imperative split.
- **Failure modes.** Socket EOF on compositor restart; partial/out-of-order initial
  state; unknown additive fields and unknown event variants (Niri's wire format
  adds fields/variants over versions and guarantees none are renamed/removed — so
  adapters must ignore-and-continue, never crash). Reconnect must rebuild
  projection from the fresh initial burst, not from stale state.
- **Privacy.** No expansion of capture surface: compositor metadata only
  (`app_id`/class, title, pid, workspace, output). No keystrokes, clipboard,
  screenshots, or arbitrary native IPC dumps. `docs/privacy.md` is the contract.
- **False unification.** The model carries only what Panopticon needs — focused
  window, app identity, title, workspace, output, and relevant transitions. This
  is a two-compositor abstraction, not a universal Wayland SDK: no plugin system,
  no dynamic registration, no capability negotiation (see D4).
- **Multi-writer store.** Raw writes rely on `O_APPEND` atomicity under `PIPE_BUF`
  (4 KiB/line). Unchanged, but the `desktop` stream inherits the assumption.

## Hypotheses

- **H1 — Niri projection is fully derivable from the event stream.** Confirmed
  against niri-ipc rustdoc: NDJSON framing, `"EventStream"` → `{"Ok":"Handled"}`
  ack → continuous events; an initial burst (`WindowsChanged`, `WorkspacesChanged`,
  `WindowFocusChanged`) delivers full state before live deltas. Global focus is a
  single `WindowFocusChanged {id: Option<u64>}`. Window→workspace→output is
  transitive (`Window.workspace_id` → `Workspace.output`); there is no `output` on
  `Window`. **Risk:** field shapes read from rendered rustdoc, not pinned source.
  *Mitigation:* pin against niri-ipc v26.4.0 before locking the projection.
- **H2 — The runner is already ~90% compositor-neutral.** Reconnect, backoff,
  logging, and all three persistence concerns are generic in `runner.py`; the only
  Sway leaks are `AsyncSession.get_tree() -> dict` and the call to the Sway
  `transform()`. Extraction is mostly deleting the leak + retiring dead duplicate
  reconnect code in `ipc.py`, not building new machinery.
- **H3 — con_id has no in-repo consumer.** The segmentizer keys focus on
  `(app_id, workspace)`; `con_id` is produced, emitted, and stored but never read
  downstream in-repo. Out-of-repo consumers are unverified — hence the
  conservative dual-emit in D2.
- **H4 — Segment tier is already neutral.** `focus-*.jsonl` / `browser-*.jsonl` —
  what SATAN reads — are compositor-independent. The schema migration touches only
  the raw tier, `current/*.json`, and the `source`/`producer` fields.
- **H5 — You run one compositor at a time.** So a single `raw/desktop-DAY.jsonl`
  stream never interleaves two producers; `producer` distinguishes historical runs.

## Decisions

- **D1 — Schema discriminator: `source:"desktop"` + `producer`.** Emit
  `source:"desktop"`, add `producer:"sway"|"niri"`, and rename the window id field
  to `window_id`. Chosen for clean semantics despite the larger blast radius: the
  store keys filenames off `source` (→ `raw/desktop-*.jsonl`, `current/desktop.json`
  fall out automatically), and the segmentizer registries (`_SOURCES`,
  `_SEGMENT_PREFIX_FOR_RAW`) plus retention's raw-name parse gain a `desktop`
  entry. Segment/histogram filenames are unchanged (already neutral, H4).
- **D2 — Conservative compatibility (con_id + current/sway.json).** Out-of-repo
  readers of the raw/current tiers are unverified (H3), so during migration:
  dual-emit `con_id` alongside `window_id`, and side-write `current/sway.json`
  beside `current/desktop.json`. Both are deprecation-window measures to drop once
  downstream state is verified — tracked as an explicit removal step in the final
  slice, not left indefinitely.
- **D3 — Niri via direct Python JSON socket.** No Rust sidecar. Connect
  `AF_UNIX/SOCK_STREAM` to `$NIRI_SOCKET`, send `"EventStream"`, assert the ack,
  read one `json.loads` per line. Projection: `windows_by_id`, `workspaces_by_id`,
  `focused_window_id`, `active_workspace_by_output`. `WindowsChanged`/
  `WorkspacesChanged` are full-state replacements; `WindowOpenedOrChanged` covers
  both open and mutation (novelty = id not yet in projection); `WindowClosed`,
  `WindowFocusChanged`, `WorkspaceActivated` are deltas. EOF → disconnect +
  reconnect + rebuild.
- **D4 — No false unification, no premature generality.** The shared model is
  exactly WindowRef/DesktopState/DesktopObservation. Compositor-specific concepts
  stay adapter-private (`DesktopObservation.fields` optional metadata) or are
  dropped. No fabricated Sway concepts in Niri (no fake tree, marks, or bindings).
  No plugin/registration/negotiation machinery for two adapters.
- **D5 — Fix the workspace/output focus bug in the Sway-extraction slice.**
  Today `_on_window_focus` (events.py:81-82) copies `workspace`/`output` from the
  *previous* state instead of deriving them from the newly focused window, so a
  focus change that crosses a workspace/output persists stale values. The Sway
  adapter must derive them from the focused window (via tree ancestry) on every
  focus event. This changes Sway output → fixtures are updated with a documented
  behaviour-change note in that slice, so Sway and Niri agree from the start.
- **D6 — Retire dead reconnect duplication.** `ipc.py`'s `stream()` generator and
  `IpcDisconnected`/`IpcReconnected`/`StreamMessage` types are an unused second
  reconnect implementation; only `run_watcher`'s loop is live. Remove them during
  the shared-runner slice rather than carry two reconnect paths into the neutral core.
- **D7 — `panopticon-desktop` entrypoint; `panopticon-sway` kept as a wrapper.**
  New shared executable with `--compositor auto|sway|niri` (auto: NIRI_SOCKET →
  niri, SWAYSOCK → sway, else fail clearly). `panopticon-sway` remains a thin
  compatibility wrapper (and `nix meta.mainProgram` must move with it or `nix run`
  breaks). `panopticon-niri` only if it materially simplifies Home Manager config —
  deferred, not decided here.

### Open questions

- **OQ-1** — Which out-of-repo consumers (waybar? SATAN? scripts in `~/flakes`)
  actually read `current/sway.json` or the `con_id` field? Answer determines how
  soon D2's compat measures can be dropped. Requires inspecting the out-of-repo
  Home Manager module and SATAN's Emacs reader.
- **OQ-2** — Do the in-repo `systemd/sway-watcher.service` unit and the out-of-repo
  HM unit get renamed to `desktop-watcher`, or does `panopticon-sway` stay the
  ExecStart during migration? Operational, resolve in the docs/migration slice.
- **OQ-3** — Exact niri-ipc v26.4.0 sub-shapes (`Timestamp`, `WindowLayout`) not
  expanded from rustdoc; pin before the Niri projection slice (H1 mitigation).
