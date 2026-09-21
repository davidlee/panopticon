# Notes SL-005: Umbriel adapter

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## D1 spike — focus derivation (2026-09-21, umbriel 0.1.0, live host)

**Question:** how to reliably identify *the* single focused window, given `focused`
is a per-window flag that is true for multiple windows at once.

**Method:** drove focus with `umbriel msg window-focus:<id>` / focus-next etc. across
and within workspaces while querying `windows --json` / `workspaces --json` and
capturing `subscribe windows,workspaces`. Fixtures: `capture-0` (within-workspace +
transient), `capture-1` (cross-workspace bounce).

**Findings:**
1. Window `focused` is **per-workspace** — exactly one focused window *per workspace
   that has one*, so ≥2 are `focused:true` whenever ≥2 workspaces are occupied. Not a
   global focus signal.
2. Window `active` is the **seat keyboard focus**: 0-or-1 across every banked frame
   (verified, never >1). Flips immediately on both within- and cross-workspace moves.
   **But transiently empties to 0** mid-transition (`capture-0` frame 4) — and can be
   persistently 0 when focus rests on a layer surface / overview.
3. `workspaces` events **do** fire on every cross-workspace focus change, but the
   `windows` event **precedes** the `workspaces` event (`capture-1`: 3→4, 5→6, 8→9,
   10→11). So a focus-via-`focused-workspace→focused-window` join **lags one frame** on
   cross-workspace jumps (join computed against the stale focused-workspace).
4. Event ordering is not guaranteed generally — a `windows` event can arrive before the
   first `workspaces` event (pre-burst). Confirms the **burst-complete gate (D2)** is
   necessary: hold emission until both families seen once.
5. **Steady state** (both snapshots settled): `active`-window and the workspace-join
   agree on exactly one window, every time (5/5 focus positions). The one-frame flaps
   are purely artifacts of recomputing on the intermediate event.

**Recommended D1 (for /design + adversarial review):** derive the focused window from
the unique **`active:true`** window (seat focus), *not* the focused-workspace join —
because `active` updates in-band on the `windows` event with no cross-family ordering
dependency, sidestepping the finding-3 flap and any multi-output focused-workspace
ambiguity (seat focus is global). Guard the transient `active==0` case:
  - previously-focused window id **still present** in the snapshot → **hold** (no emit);
  - previously-focused window id **gone** (closed) → emit de-focus (`window=None`).
Consume `workspaces` for the workspace→output mapping and workspace-level observations,
and take the focused window's `workspace`/`output` from its own `workspace` id joined to
`workspaces[].output` — **not** as the focus-window authority. This is a stronger,
evidence-backed variant of niri's DL-6 (focus-through-workspace); the mechanism differs
because umbriel exposes seat focus directly via `active`.

**Residual (small):** multi-output focused-workspace behaviour not exercised (single
DP-3 host) — the `active`-primary rule is expected to be robust to it precisely because
seat focus is global; note for the design to state, not a blocker.
