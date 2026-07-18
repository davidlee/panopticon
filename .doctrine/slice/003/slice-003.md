# Niri adapter

## Context

Realises SPEC-001 (`references --role implements`); `needs SL-002` (the neutral core
+ adapter contract must exist first). Adds Niri as a second peer adapter behind the
`CompositorSession` contract SL-002 defined — a greenfield external-protocol adapter,
a fundamentally different risk profile from SL-002's behaviour-preserving refactor,
and independently shippable.

Protocol confirmed by the SPEC-001 review (H1, D3): NDJSON over `$NIRI_SOCKET`,
`"EventStream"` → `{"Ok":"Handled"}` → event stream; pin niri-ipc `=26.4.0` (not
semver-stable). Window→workspace→output is transitive (no `output` on Window). IDs are
opaque, stable only while open (D11). Projection is an order-independent accumulator.

## Scope & Objectives

**Delivery boundary (locked at `/design`, 2026-07-18):** the Niri adapter **plus**
the minimum live wire-up for data to flow again — because Niri is live and the Sway
watcher is dormant (`mem.fact.panopticon.niri-live-sway-dead`), an adapter alone
delivers no live value. See `design.md §1`.

Provisional phase breakdown (finalise at `/plan`):

1. **Protocol + projection.** `compositor/niri/{protocol,projection}.py`: socket
   framing + ack, one `json.loads` per line; projection `windows_by_id`,
   `workspaces_by_id`, `focused_workspace_id`. `WindowsChanged`/`WorkspacesChanged`
   full-state; `WindowOpenedOrChanged` open-or-mutate (novelty = id unseen);
   `WindowClosed`/`WorkspaceActivated`/`WorkspaceActiveWindowChanged` deltas. Focus
   derives from the focused workspace's `active_window_id`, so `WindowFocusChanged`
   and `OverviewOpenedOrClosed` are ignored — overview is inert by construction
   (design DL-6, golden-capture-driven). Burst-completion = both full-state events
   applied (DL-2); empty snapshot valid; partial burst discarded; reconnect emits
   the neutral snapshot + disconnect pair. Ignore-and-continue on unknown
   fields/variants.
2. **Normalization + equivalence.** Emit normalized snapshot + observations; focus/
   title (diff-based per D10)/workspace/output correctness; emit-time timestamps (D9,
   ignore niri's `Timestamp`); EOF/reconnect + cross-compositor equivalence tests
   proving Niri and Sway produce comparable DesktopObservations.
3. **Live wire-up.** Complete `compositor/detect.py`'s D7 resolution (wire the niri
   client into `select_client`, connect-validated `auto` probe replacing the RV-001
   F-1 `SWAYSOCK` stand-in, both-set → niri) and widen `segmentizer/histogram.py`
   (R4) so Niri's per-output workspaces do not conflate. `--compositor auto` runs
   Niri live end-to-end.

## Non-Goals

- Changes to the neutral **model/runner/events** or the Sway adapter, and any
  **event-schema** change (all owned by SL-002). *Exception (in-scope):*
  `detect.py`'s D7 completion — SPEC-001 D7 names SL-003 as its owner — and
  `histogram.py`'s R4 de-conflation, which the SL-002 audit deferred to SL-003.
  Neither alters the neutral event schema; the histogram key-shape change is
  SATAN-code-safe (`activity_read` forwards the dict verbatim — design.md §5.4).
- Docs, unit renames, compat retirement, and SATAN's semantic coordination with the
  new `"output/workspace"` histogram keys (SL-004).
- Niri-native concepts (columns, named workspaces) in the shared model (D4).
- A dedicated `panopticon-niri` entrypoint (D7 — deferred, not decided).

## Summary

Niri behind the SL-002 contract: direct JSON-socket adapter + projection normalizing
to shared observations, with the review's failure rules baked in.

## Follow-Ups

- **OQ-5 resolved at `/design`:** hybrid fixtures — two live golden host captures
  (burst+empty-workspace, overview flap) + hand-authored edge cases, pinned to
  niri-ipc `=26.4.0` (design.md §9).
- **Q1 / ASM-1 (design→plan gate) — CLOSED 2026-07-18:** golden captures confirm
  `output` = DRM connector name (`"DP-3"`, SPEC-001 D4). The captures also revised
  the burst terminator (DL-2) and the focus model (DL-6); design is locked (design.md
  §6, §10).
</content>
