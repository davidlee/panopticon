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
entrypoint. Downstream: the store and SATAN change only for the
`source`/`producer`/`window_id` schema migration; the segmentizer changes more
than first assumed — it carries a hardcoded `source:"sway"` and a literal
`sway_disconnected` event-name dependency, and its focus key gains a `producer`
dimension (see D1, D8, and the downgraded H4).

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
  projection from the fresh initial burst, not from stale state. Two Niri-specific
  hazards the shared deriver must not be polluted by (see D3): a **partial initial
  burst** (socket dies mid-burst) must be discarded, not emitted as a half-built
  snapshot; and `WindowFocusChanged {id: None}` (overview open, or all windows
  closed) must map to a *continuation* state, not a segment-closing focus-loss —
  else toggling the overview flaps the segment stream, a failure Sway does not have.
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

- **H1 — Niri projection is fully derivable from the event stream.** CONFIRMED
  (adversarial review, 2026-07-13) against niri-ipc rustdoc + wiki + `lib.rs`:
  NDJSON framing, `"EventStream"` → `{"Ok":"Handled"}` ack → continuous events; an
  initial burst delivers full state (each category's *first* event is its full-state
  variant) before live deltas. Global focus is a single
  `WindowFocusChanged {id: Option<u64>}`. Window→workspace→output is transitive
  (`Window.workspace_id: Option<u64>` → `Workspace.output: Option<String>`); there
  is no `output` on `Window`. Additive-only stability is a *documented* guarantee
  (existing fields/variants never renamed or removed). Two corrections from the
  review: (a) window ids are opaque `u64`, stable **only while the window is open**
  — the docs guarantee neither ordering, start value, nor cross-lifetime reuse, so
  assume nothing (the novelty test survives: `WindowClosed` removes the id first);
  (b) the cross-category burst order (`WindowsChanged`/`WorkspacesChanged`/
  `WindowFocusChanged`) is **not** guaranteed — the projection must be an
  order-independent accumulator. **OQ-3 closed:** v26.4.0 is the current latest
  (published 2026-07-10) and the crate is deliberately not semver-stable, so the
  exact `=` pin is *required*; the two unexpanded sub-shapes (`Timestamp{secs,nanos}`,
  `WindowLayout` geometry) are irrelevant to a focus/title/workspace/output watcher.
- **H2 — The runner is ~90% neutral, but snapshot acquisition inverts from pull to
  push (revised).** Reconnect, backoff, logging, and the three persistence concerns
  are generic in `runner.py`. But the leak is larger and structural, not a simple
  deletion: beyond `get_tree()` and `transform()`, `process_session`
  (runner.py:67-73) is *pull*-shaped — one atomic `get_tree()` → `focus_state_from_tree`
  → emit `snapshot`. Niri has no `get_tree`; its initial state is a *push* burst
  with no terminator, so the pull model cannot be reused. The neutral contract must
  invert: **the adapter's session yields its own initial `snapshot` observation**
  (Sway calls `get_tree` internally; Niri accumulates the burst internally), and
  `process_session` stops calling `get_tree` at all. Also Sway-labelled and in the
  rename blast radius: the three synthetic `source="sway"` event factories
  (runner.py:72/109/119 → events.py:194/199/203), logger `"panopticon.sway"` (:37),
  `AsyncSwayClient` (:49). Still true: retiring the dead `ipc.py` reconnect (D6).
- **H3 — con_id has NO consumer, in- or out-of-repo (confirmed via OQ-1).** The
  segmentizer keys focus on `(app_id, workspace)`; `con_id` is produced, emitted, and
  stored but never read. OQ-1 (2026-07-13, out-of-repo trees now mounted) confirms no
  reader out-of-repo either: no source file keys on `con_id`; SATAN passes the
  current-window object through verbatim (`satan-tools-activity.el:110-115`,
  `satan-memory-evidence.el:132-148`); the raw tier (`raw/*.jsonl`) has no programmatic
  out-of-repo reader at all. → `con_id` can be dropped outright; the dual-emit half of
  D2 is retired.
- **H4 — Segment *pipeline* is neutral; segment *data* is not (downgraded).** The
  original claim (segment tier fully neutral, migration touches only raw +
  `current/*.json`) is FALSE — the review found two segment-tier couplings: (a)
  `derive.py:35` hardcodes `source:"sway"` into every segment record body (SATAN
  reads the `source` field), and (b) `derive.py:82` closes a focus segment only on
  the literal event name `"sway_disconnected"` — an implicit event-name API. Rename
  the disconnect event and segments silently stop closing on compositor restart, so
  the neutral watcher must keep emitting the exact event names the deriver keys on
  (`snapshot`, `window_focus`, `workspace_focus`, `sway_disconnected` — derive.py:69/75/82).
  Deeper, the focus key `(app_id, workspace)` (derive.py:69-74) is *value*-dependent
  on the compositor: Niri workspaces are per-output, dynamic, and usually UNNAMED, so
  two distinct workspaces (output A idx 1, output B idx 1) collapse to the same
  neutral `"1"` and collide; XWayland `app_id` strings also differ (Sway
  `window_properties.class` vs Niri via xwayland-satellite). → cross-compositor
  histogram conflation. Addressed by D8 (add `producer`/`output` to the key). What
  *is* still true: segment/histogram *filenames* carry no compositor literal.
- **H5 — You run one compositor at a time.** So a single `raw/desktop-DAY.jsonl`
  stream never interleaves two producers; `producer` distinguishes historical runs.
  (Does not rescue H4's key collision: two Niri workspaces collide within a single
  producer's stream, independent of switching.)

## Decisions

- **D1 — Schema discriminator: `source:"desktop"` + `producer`.** Emit
  `source:"desktop"`, add `producer:"sway"|"niri"`, and rename the window id field
  to `window_id`. **Rationale (revised after review):** there *is* a single
  downstream consumer (SATAN) that wants attention data regardless of which
  compositor produced it. Unification therefore happens somewhere; the choice is
  *where*. We consolidate at the **storage/producer layer** — the adapter boundary
  already computes neutral observations, so persisting a neutral `source` just
  writes down what we derived once. The alternative — sibling `source:"sway"|"niri"`
  streams unified by a downstream adapter — re-derives neutrality a *second* time
  and hands compositor knowledge back to the consumer we worked to keep clean (a
  parallel implementation of the adapter-boundary neutralization). `producer`
  retains the provenance that a single `source` would otherwise erase. (The earlier
  "store keys filenames off `source`" justification was weak — filenames fall out
  either way; the real driver is unify-once-at-the-producer.) Blast radius: store
  filenames fall out automatically (`raw/desktop-*.jsonl`, `current/desktop.json`);
  the segmentizer registries `_SOURCES` and `_SEGMENT_PREFIX_FOR_RAW` gain a
  `desktop` entry (retention's `_source_from_raw_name` is already generic — no
  change); every `make_event("sway", …)` becomes producer-parameterized. Segment
  *record bodies* also change (H4) — see D8.
- **D2 — Compatibility: side-write `current/sway.json` only; drop con_id (resolved
  by OQ-1).** OQ-1 (2026-07-13) inventoried the now-mounted out-of-repo trees and
  split the original conservative measure cleanly:
  - **con_id — DROPPED.** No reader anywhere (H3). No dual-emit; `con_id` is removed
    from the raw tier, not carried.
  - **`current/sway.json` — KEEP the side-write.** Four out-of-repo readers hard-code
    the filename (`satan-tools-activity.el:111`, `satan-memory-evidence.el:662` +
    mtime staleness at :100/:132, `satan-sensor-alerts.el:120` shell `head -1
    ~/.local/state/behaviour/current/sway.json`, `.emacs.d/lisp/dl-sleipnir-doctor.el:266`).
    Content is consumed verbatim, so the internal id-field rename to `window_id` is
    harmless — but the *filename* and the `~/.local/state/behaviour/current/` path are
    load-bearing. During migration, side-write `current/sway.json` beside
    `current/desktop.json`. This is the only compat surface; it lives in the store
    write path, not the neutral event encoder. Drop it once SATAN is updated to read
    `current/desktop.json` across those four sites (a cross-repo change tracked
    separately, not gating this spec).
- **D3 — Niri via direct Python JSON socket.** No Rust sidecar. Connect
  `AF_UNIX/SOCK_STREAM` to `$NIRI_SOCKET`, send `"EventStream"`, assert the ack,
  read one `json.loads` per line. Projection: `windows_by_id`, `workspaces_by_id`,
  `focused_window_id`, `active_workspace_by_output`. `WindowsChanged`/
  `WorkspacesChanged` are full-state replacements; `WindowOpenedOrChanged` covers
  both open and mutation (novelty = id not yet in projection); `WindowClosed`,
  `WindowFocusChanged`, `WorkspaceActivated` are deltas. EOF → disconnect +
  reconnect + rebuild. **Failure rules (from review):** (a) *burst completion* —
  buffer the initial burst and emit the first `snapshot` only on the first
  `WindowFocusChanged`; if the socket dies before it, discard the partial session,
  do not emit a half-built snapshot; (b) *`WindowFocusChanged {id: None}`* (overview
  / all-closed) maps to a defined neutral state the deriver treats as continuation,
  not focus-loss (no segment close — avoids overview flapping); (c) on every
  reconnect emit the neutral `snapshot` + `compositor_disconnected` pair so the
  deriver's close/reopen matches Sway; (d) *title diff* —
  `WindowOpenedOrChanged` fires on any mutation (title, resize, column move), so a
  neutral `window_title` change is emitted only when the projection's `title` field
  actually changes; geometry/layout mutations emit nothing (see D10).
- **D4 — No false unification, no premature generality.** The shared model is
  exactly WindowRef/DesktopState/DesktopObservation. Compositor-specific concepts
  stay adapter-private (`DesktopObservation.fields` optional metadata) or are
  dropped. No fabricated Sway concepts in Niri (no fake tree, marks, or bindings).
  No plugin/registration/negotiation machinery for two adapters. **Workspace/output
  neutrality (from review):** the review flagged that a bare `workspace: str` is
  secretly Sway-shaped (Sway workspaces are globally-unique named strings; Niri's
  are per-output, dynamic, usually unnamed) — the neutral model must therefore carry
  `output` as a first-class disambiguating dimension alongside `workspace`, not fold
  it away. `output` is the DRM connector name (e.g. `"eDP-1"`) for **both** producers
  — asserted here as a decision, to be verified against a live Niri before the Niri
  slice locks. This keeps the model thin without being Sway-shaped, and gives D8 the
  key it needs.
- **D5 — Fix the workspace/output focus bug via a Sway tree-projection (revised).**
  Today `_on_window_focus` (events.py:81-82) copies `workspace`/`output` from the
  *previous* state instead of deriving them from the newly focused window, so a
  focus change that crosses a workspace/output persists stale values. The fix is
  **architecturally load-bearing, not incidental** (review): the focus-event payload
  carries no ancestry, so deriving workspace/output on every focus event requires
  either a per-focus `get_tree()` round-trip (an async IPC call inside what is
  currently a pure `transform` — violates the purity split) or the Sway adapter
  maintaining a **live tree projection** (mirroring the Niri adapter). We choose the
  projection: the Sway adapter holds its own state and derives workspace/output from
  the focused window on each event — which also makes Sway and Niri structurally
  symmetric (both are projection adapters; D5 is the mechanism, not a patch). Because
  this is a deliberate behaviour change bundled with a behaviour-preserving move, it
  gets its **own before/after test** isolating the fix from mechanical-extraction
  drift, and fixtures are updated with a documented behaviour-change note — so the
  "fixtures stay green" gate stays legible.
- **D6 — Retire dead reconnect duplication.** `ipc.py`'s `stream()` generator and
  `IpcDisconnected`/`IpcReconnected`/`StreamMessage` types are an unused second
  reconnect implementation; only `run_watcher`'s loop is live. Remove them during
  the shared-runner slice rather than carry two reconnect paths into the neutral core.
  (Review caveat: `test_sway_ipc.py` exercises `stream`/`Ipc*` — those tests are
  deleted with the code; production has no importer.)
- **D7 — `panopticon-desktop` entrypoint; `panopticon-sway` kept as a wrapper.**
  New shared executable with `--compositor auto|sway|niri`. **Auto-detection
  (tightened after review):** env-var *presence* is a hint, not liveness — resolve
  by attempting to connect. If both `NIRI_SOCKET` and `SWAYSOCK` are set (nested /
  XWayland / a stale var from a dead session), try each socket and use the one that
  actually connects; if both connect, prefer `NIRI_SOCKET` (stated explicitly, not
  left to list order); if neither connects, fail clearly listing what was tried.
  `panopticon-sway` remains a thin compatibility wrapper (and `nix meta.mainProgram`
  must move with it or `nix run` breaks). `panopticon-niri` only if it materially
  simplifies Home Manager config — deferred, not decided here.
- **D8 — Focus segment key gains a `producer` (and `output`) dimension.** Because
  segment *data* is compositor-dependent (H4 downgraded), the focus deriver key
  changes from `(app_id, workspace)` to `(producer, output, app_id, workspace)` so
  Niri's per-output unnamed workspaces and producer-divergent `app_id` cannot
  conflate in histograms. Touches `segmentizer/derive.py` (key + the hardcoded
  `source:"sway"` at :35), the focus segment schema, and histogram aggregation.
  Chosen over "accept per-compositor-era histograms and document it" (owner
  decision, 2026-07-13) — correctness over cheapness.
- **D9 — Timestamp is the watcher's emit/receive time for both producers.** Sway
  i3ipc events carry no timestamp, so `schema.utc_now_iso()` already stamps at emit
  time. Niri events *do* carry a `Timestamp`, but using it for Niri only would make
  `duration_s` (derive.py:94-95) mean different things per producer. Decision: ignore
  Niri's event `Timestamp`; stamp at emit time for both, keeping duration semantics
  uniform.
- **D10 — Neutral events are projection *diffs*, not raw native events.** Both
  adapters emit a neutral event only when the projected value changes:
  `window_title` on a title-field change, `window_focus` on a focus change, etc.
  Niri's `WindowOpenedOrChanged` (fires on resize/move too) and Sway's native events
  are inputs to the projection, never emitted verbatim — this bounds event volume
  and keeps the two producers' emission semantics identical.
- **D11 — `window_id` uniqueness is scoped, not global-in-time.** Both Sway
  `con_id` and Niri ids are opaque and may recur across window lifetimes (H1).
  `window_id` is unique only within `(producer, window-lifetime)`, never a stable
  cross-time key. Moot in practice (H3 confirms no consumer keys on it, and con_id is
  dropped per D2/OQ-1) — recorded so no future consumer mistakes it for a durable id.

### Open questions

- **OQ-1** — CLOSED (2026-07-13, out-of-repo trees mounted at `/workspace/{flakes,satan,.emacs.d}`).
  `con_id`: no reader anywhere → dropped. `current/sway.json`: four hard-coded readers
  (SATAN activity tool, evidence-window assembly + staleness, sensor-alerts shell
  path, sleipnir doctor) consume it verbatim → keep the side-write, drop once SATAN is
  repointed. Folded into D2 + H3.
- **OQ-2** — Do the units get renamed to `desktop-watcher`? Partly answered by OQ-1:
  the producer unit `systemd.user.services.panopticon-sway`
  (`flakes/modules/home/linux/behaviour.nix:21`) sets `ExecStart = ${lib.getExe
  panopticon}` — driven by `nix meta.mainProgram`, so it is **rename-safe as long as
  D7's mainProgram move holds**; the unit *name* is a cosmetic label. Sibling units
  `panopticon-segmentize`/`panopticon-git` use explicit `/bin/…` paths (unchanged
  binaries). Remaining decision (unit-name cosmetics) still deferred to the
  docs/migration slice. NOTE: the live module path is `home/linux/`, not `home/nixos/`
  as the recon notes first guessed.
- **OQ-3** — CLOSED (adversarial review, 2026-07-13). niri-ipc v26.4.0 is the current
  latest; the crate is not semver-stable so the exact `=` pin is required.
  `Timestamp{secs,nanos}` and `WindowLayout` (geometry) are irrelevant to this
  watcher — see H1. Folded into D9/D10.
- **OQ-4** — Migration-day historical-data retirement. On cutover the state dir holds
  both `raw/sway-*.jsonl` and `raw/desktop-*.jsonl`, and Sway raws stay within the
  7-day retention window (retention.py:43). If the `sway` `_SOURCES` entry is
  *replaced* rather than *kept*, the segmentizer stops globbing sway raws while the
  reaper's optimistic fallback (retention.py:105-108) still deletes them →
  un-segmented data silently reaped. Decision (resolve in the migration slice): keep
  the `sway` segmentizer/retention entries alive on a retirement **dated to raw
  retention**, decoupled from the D2 compat drop; add a migration-day equivalence
  test.
- **OQ-5** — Niri test-fixture capture. Concerns §Purity and the Niri slices need a
  recorded-NDJSON fixture corpus, but the capture method (record a live session vs
  hand-author) and its version-pin against niri-ipc v26.4.0 are undecided — the same
  rustdoc-vs-source risk H1 flagged, at the test layer. Resolve before the Niri
  projection slice.
