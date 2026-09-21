# Umbriel adapter

## Context

Realises SPEC-001 (`references --role implements`); `needs SL-002` (the neutral core
+ `CompositorSession`/`CompositorClient` contract must exist first). Adds Umbriel as a
third peer adapter behind the SL-002 contract, alongside niri (SL-003) and sway
(SL-002) — a greenfield external-protocol adapter, same risk profile as SL-003.

Umbriel is Noctalia's compositor; its IPC is documented at
`https://docs.noctalia.dev/umbriel/ipc/` — early and fast-moving, so the design is
**golden-capture-driven** (as SL-003 was), pinned to a captured umbriel build.

Protocol confirmed by live capture (2026-09-21, `windows` query + a `subscribe
windows workspaces` transcript — both banked as fixtures):

- **Transport:** line-delimited JSON over a unix socket. Path = `$UMBRIEL_SOCKET`,
  else `$XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock`.
- **Subscribe = immediate burst.** `{"cmd":"subscribe","events":["windows","workspaces"]}`
  emits a full `windows` snapshot then a full `workspaces` snapshot on connect, then
  streams. No ack to assert; no query-seeding. Pure streaming, like niri's EventStream.
- **Every event is a full snapshot** (`{"event":"<family>","data":[…]}`) matching the
  corresponding query response — identical consecutive payloads coalesced. So the
  projection is snapshot-replace, **not** a delta accumulator: niri's burst-gate and
  novelty detection do not exist here.
- **Focus is per-workspace; seat focus is `active`.** `focused` is a *per-workspace*
  window flag — multiple windows carry `focused:true` at once (one per workspace column),
  so it is not a global signal. **[Superseded by the D1 spike — see design DL-4:** the
  spike reversed this scoping guess. The seat's keyboard focus is the window `active`
  flag (0-or-1 globally, primary), with the focused-workspace→focused-window join as a
  pure fallback only. The pre-spike "use the workspace→window join, `active` is
  unreliable" note below is wrong.**]**
- **Data model joins cleanly.** Window carries `workspace` (a composite `"DP-3:1"` =
  `output:<opaque-id>`, empty when scratchpad — the suffix is an internal id, **not** the
  display index: `DP-3:17` has `index:2`); workspace carries `output` (DRM connector,
  e.g. `"DP-3"`). Window→workspace→output is transitive. IDs are opaque strings, stable
  while open.

## Scope & Objectives

Deliver the Umbriel adapter **plus** the minimum live wire-up so `--compositor umbriel`
(and `auto`) run end-to-end — mirroring SL-003's delivery boundary (an adapter alone
delivers no live value).

Provisional phase breakdown (finalise at `/plan`):

1. **Protocol + projection.** `compositor/umbriel/{protocol,projection}.py`: socket
   discovery (`$UMBRIEL_SOCKET` → derived path), connect + subscribe framing, one
   `json.loads` per line. Projection holds latest `windows[]` + `workspaces[]`;
   `to_state()` derives focus via the focused-workspace→focused-window join, then
   window→workspace→output. First-snapshot gate = both families seen once (burst
   complete); thereafter each event replaces its half. Total/pure, ignore-and-continue
   on unknown fields/families.
2. **Normalization + equivalence.** Emit neutral snapshot + observations; focus /
   title (diff-based) / workspace / output correctness; emit-time timestamps;
   EOF/reconnect + cross-compositor equivalence tests proving Umbriel, niri and sway
   produce comparable `DesktopObservation`s. `session.py` clones niri's snapshot-first
   `observations()` + `diff_state` precedence (workspace_focus > window_focus >
   window_title).
3. **Live wire-up.** Extend `compositor/detect.py` to a three-way `auto` probe
   (niri / sway / umbriel, connect-validated) and add `"umbriel"` to the CLI
   `--compositor` choices. `--compositor auto` runs Umbriel live end-to-end.

## Non-Goals

- Changes to the neutral **model/runner/events/schema** (owned by SL-002) — a new
  adapter is a new `producer` value, not a schema reshape.
- Umbriel-native concepts in the shared model: **scratchpad** membership, `floating`,
  `content_type`, `xdg_tag`, `layout` mode, submap/theme/keyboard_layout event families
  (default: subscribe only to `windows` + `workspaces`; ignore the rest). Mirrors niri's
  D4 (native concepts stay out of the neutral model).
- A dedicated `panopticon-umbriel` entrypoint (optional compat wrapper — defer unless
  a driver needs it, per SL-003's D7 stance).

## Summary

Umbriel behind the SL-002 contract: a direct JSON-socket adapter whose snapshot
projection normalizes to shared observations. Lighter than SL-003 — snapshots replace
the delta engine and burst-gate — with focus at parity (the transitive
workspace→window join).

## Follow-Ups

- **Golden fixtures banked (2026-09-21):** `windows` query + `subscribe windows
  workspaces` transcript from a live host. Confirmed: immediate subscribe burst,
  full-snapshot events, per-workspace `focused`, `output:<opaque-id>` workspace ids
  (suffix ≠ display index — spike/design DL-1/ASM-U2).
- **Open (resolve at `/design`, low risk):** no capture of an actual *workspace switch*
  — confirm it fires a `workspaces` event (expected, since window-focus-within-workspace
  fires `windows`). Nail `active` vs `focused` window-flag semantics from the fixtures.
- **Version pinning:** no protocol versioning; unknown subscribe families error
  immediately (fail-fast on typo). Pin fixtures to the captured umbriel build; no
  library dependency (stdlib `json`, as niri).
