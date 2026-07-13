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

Provisional phase breakdown (finalise at `/plan`):

1. **Protocol + projection.** `compositor/niri/{protocol,projection}.py`: socket
   framing + ack, one `json.loads` per line; projection `windows_by_id`,
   `workspaces_by_id`, `focused_window_id`, `active_workspace_by_output`.
   `WindowsChanged`/`WorkspacesChanged` full-state; `WindowOpenedOrChanged`
   open-or-mutate (novelty = id unseen); `WindowClosed`/`WindowFocusChanged`/
   `WorkspaceActivated` deltas. D3 failure rules: burst-completion (buffer to first
   `WindowFocusChanged`; partial burst discarded), `focus id:None` → continuation not
   close, reconnect emits the neutral snapshot + disconnect pair. Ignore-and-continue
   on unknown fields/variants.
2. **Normalization + equivalence.** Emit normalized snapshot + observations; focus/
   title (diff-based per D10)/workspace/output correctness; emit-time timestamps (D9,
   ignore niri's `Timestamp`); EOF/reconnect + cross-compositor equivalence tests
   proving Niri and Sway produce comparable DesktopObservations.

## Non-Goals

- Any change to the neutral core / Sway adapter / schema (owned by SL-002).
- Docs, unit renames, compat retirement (SL-004).
- Niri-native concepts (columns, named workspaces) in the shared model (D4).
- A dedicated `panopticon-niri` entrypoint (D7 — deferred, not decided).

## Summary

Niri behind the SL-002 contract: direct JSON-socket adapter + projection normalizing
to shared observations, with the review's failure rules baked in.

## Follow-Ups

- OQ-5 (Niri test-fixture capture method + version-pin) must be resolved at this
  slice's `/plan` — recorded NDJSON corpus vs hand-authored, pinned to `=26.4.0`.
</content>
