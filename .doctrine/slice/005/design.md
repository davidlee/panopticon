# Design SL-005: Umbriel adapter

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-005, SPEC-001, ADR-nnn); doc-local refs bare — OQ-1 (§6), D1 (§7).
     Decisions inherited from SPEC-001 are cited as SPEC-001 Dn; decisions local
     to this slice are DL-n. SL-003 (niri) is the structural template throughout. -->

## 1. Design Problem

Add **Umbriel** (Noctalia's wayland compositor, `0.1.0`) as a third peer adapter
behind the `CompositorSession` contract SL-002 defined, alongside niri (SL-003) and
sway (SL-002). The user has switched window managers again; an adapter restores live
desktop-attention data on the new host. Like SL-003 this is a greenfield
external-protocol adapter whose only in-jail verification surface is fixtures.

Delivery boundary (locked this design): the Umbriel adapter **plus** the live wire-up
for data to flow — extending `detect.py` to a three-way connect-validated probe and
adding `"umbriel"` to the CLI. **No histogram change is needed** — SL-003's R4 already
keyed `per_workspace_seconds` on `"output/workspace"`, and Umbriel always carries
`output`, so it inherits correct de-conflation for free.

## 2. Current State

SL-002 + SL-003 shipped the neutral core and two adapters:

- **Contract** (`compositor/model.py`): `WindowRef`, `DesktopState`,
  `DesktopObservation`; `CompositorSession.observations() -> AsyncIterator`
  (snapshot-first, the pull→push inversion); `CompositorClient{producer, session()}`.
- **Runner** (`compositor/runner.py`): `process_session` (encode + store, no state
  threading) and `run_watcher` (reconnect/backoff; emits neutral
  `compositor_disconnected`/`compositor_reconnected`; the fresh session supplies the
  post-reconnect snapshot).
- **Encoder** (`compositor/events.py`): `encode(obs, producer)` — sole `source`/
  `producer` injector (INV-2).
- **Adapters** (`compositor/{sway,niri}/`): two projection sessions behind the
  contract. Niri is the closest template — a pure streaming push adapter
  (`protocol.py` framing, `projection.py` accumulator, `session.py` burst-gate + diff).
- **Detection** (`compositor/detect.py`): `select_client(compositor)` maps
  `sway|niri|auto`; `_auto_select` connect-validated-probes `NIRI_SOCKET` then
  `SWAYSOCK`, niri preferred on tie. Adapter imports deferred so `--help` works with no
  IPC stack.
- **Segment tier**: focus key `(producer, output, app_id, workspace)`;
  `histogram.py::aggregate` buckets `per_workspace_seconds` on `f"{output}/{workspace}"`
  when the segment carries `output`, else bare `workspace` (SL-003 DL-5). Umbriel
  segments carry `output` → keyed `"DP-3/emacs"`, no change required.

Umbriel is unreachable from the build jail; its socket lives on the host. **Two live
host captures are already banked** under `tests/fixtures/umbriel/` (§9) — the D1 spike
recorded them.

## 3. Forces & Constraints

- **Pure/imperative split** (project doctrine): native decode, projection, and
  observation construction are pure and unit-testable without a live compositor; socket
  I/O, framing, reconnect live in the thin async shell.
- **Behaviour-preservation gate**: SL-002/SL-003 suites stay green unchanged. The
  neutral core, event schema, sway/niri adapters, and `histogram.py` are **not**
  touched. Only `detect.py` (probe extension) + the CLI `choices` change outside
  `compositor/umbriel/`.
- **No live compositor in-jail**: fixtures are the sole in-jail verification. Fidelity
  to the real wire format is the central risk — closed the same way SL-003 closed it,
  by live golden capture (§9).
- **Umbriel wire stability**: `0.1.0`, early and fast-moving. No protocol versioning;
  unknown subscribe families error immediately (fail-fast on typo). Adapters
  **ignore-and-continue** on unknown event families/fields, never crash. Wire-format
  provenance pinned in the fixture header (no package dependency — stdlib `json`).
- **Privacy** (`docs/privacy.md`): compositor metadata only — app_id, title, pid,
  workspace, output. No new capture surface.
- **One compositor at a time** (SPEC-001 H5): a single `raw/desktop-DAY.jsonl` never
  interleaves two producers; `producer` is constant intra-day.

## 4. Guiding Principles

- **Structural symmetry with niri.** Both are pure streaming push adapters behind the
  same contract (SPEC-001 D5). Reuse the `protocol`/`projection`/`session` shape.
- **Snapshots, not deltas.** Umbriel emits a full snapshot per event; the projection
  is a *replace*, not an accumulator. Niri's novelty detection, `WindowClosed` id-drop,
  and burst-order permutations **do not exist here** — a subtraction, not an addition.
- **Neutrality is subtraction** (SPEC-001 D4). The projection surfaces only the neutral
  `WindowRef`/`DesktopState`; umbriel-native concepts (scratchpad, floating, layout
  mode, submap/theme/keyboard_layout families) never leak up.
- **Purity first.** Focus derivation is a total pure function of the *latest* windows +
  workspaces snapshots. No prior-state "hold" — the two-tier rule (D1) is pure.

## 5. Proposed Design

### 5.1 System Model

```
compositor/umbriel/
  protocol.py    IMPURE — resolve socket path ($UMBRIEL_SOCKET, else
                 $XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock); AF_UNIX/SOCK_STREAM;
                 send {"cmd":"subscribe","events":["windows","workspaces"]}; yield one
                 json.loads() per line. NO ack to assert — the stream opens directly
                 with the burst. (The niri/protocol.py analogue; deferred import.)
  projection.py  PURE — UmbrielProjection: latest windows[] + workspaces[] (replace on
                 each event) + to_state(): two-tier focus (D1) + transitive
                 window→workspace→output lookup.
  session.py     UmbrielSession(CompositorSession) + UmbrielClient(CompositorClient):
                 burst-completion gate (D2), diff emission (SPEC-001 D10).
                 Snapshot-first observation stream.
```

Data flow:

```
socket → protocol.frames() → UmbrielSession:
    burst mode: apply(event)*  → once BOTH "windows" and "workspaces" seen once (D2):
        yield DesktopObservation("snapshot", …)
    live mode:  apply(event) → diff to_state() vs prior → yield
        workspace_focus / window_focus / window_title   (neutral names, D10)
    EOF → generator returns → run_watcher emits compositor_disconnected + backoff
```

`run_watcher` supplies lifecycle events and snapshot-first reconnect (SPEC-001 D3c)
unchanged — SL-005 adds no lifecycle-event code.

### 5.2 Interfaces & Contracts

```python
# protocol.py (impure shell)
def resolve_socket() -> str:
    """$UMBRIEL_SOCKET, else f"{$XDG_RUNTIME_DIR}/umbriel-{$WAYLAND_DISPLAY}.sock"."""
async def frames(sock_path: str, *, connect_timeout: float = 2.0) -> AsyncIterator[dict]:
    """Connect, send the subscribe request, yield json.loads()/line. No ack. Raises on
    connect failure → run_watcher turns it into a disconnect. Connect + first read are
    bounded by connect_timeout so a wedged umbriel fails fast."""

# projection.py (pure)
@dataclass(frozen=True, slots=True)
class UmbrielWindow:      # adapter-private; only the neutral subset is surfaced
    id: str; app_id: str | None; pid: int | None; title: str | None
    workspace: str | None       # workspace *id* ("DP-3:1"), "" ⇒ scratchpad
    active: bool; focused: bool  # active = seat focus (0/1 globally); focused = per-ws
@dataclass(frozen=True, slots=True)
class UmbrielWorkspace:
    id: str; name: str | None; named: bool; index: int
    output: str | None; focused: bool
@dataclass(frozen=True, slots=True)
class UmbrielProjection:
    windows:    tuple[UmbrielWindow, ...]    = ()
    workspaces: tuple[UmbrielWorkspace, ...] = ()
    seen_windows: bool = False        # burst-gate halves (D2)
    seen_workspaces: bool = False
    def apply(self, event: dict) -> "UmbrielProjection": ...   # total, ignore-unknown
    @property
    def burst_complete(self) -> bool: return self.seen_windows and self.seen_workspaces
    def to_state(self) -> DesktopState: ...

# session.py (impure glue)
class UmbrielSession:   # CompositorSession
    async def observations(self) -> AsyncIterator[DesktopObservation]: ...
class UmbrielClient:    # CompositorClient
    producer = "umbriel"
    def session(self) -> AbstractAsyncContextManager[UmbrielSession]: ...
```

**Event → mutation** (`apply`; unknown families/fields ignored):

| umbriel event | mutation |
|---|---|
| `{"event":"windows","data":[…]}` | replace `windows` (full snapshot); `seen_windows = True` |
| `{"event":"workspaces","data":[…]}` | replace `workspaces` (full snapshot); `seen_workspaces = True` |
| `theme`, `overview`, `keyboard_layout`, `submap`, any unknown family | **ignored** (not subscribed; if seen, no-op — INV-U1) |

No per-window delta events exist: a window open/close/move/retitle arrives as the next
full `windows` snapshot. This is why there is no novelty detection and no `WindowClosed`
handling (contrast niri §5.2).

**`to_state()` — two-tier focus (D1) + transitive lookup.** Pure; a function of the
latest snapshots only:

```
# Tier 1 — the seat's keyboard focus (verified 0-or-1 globally, never >1):
aw = the unique w in windows where w.active            # None if 0 active
# Tier 2 — fallback when active is momentarily empty (transient) OR focus rests on a
#          layer surface (persistent): the focused window on the focused workspace.
if aw is None:
    fws = the unique ws in workspaces where ws.focused  # None if 0 or >1
    aw  = the unique w in windows where w.focused and w.workspace == fws.id  if fws else None
# Derive:
if aw is None:  → DesktopState()                        # genuine no-focus
ws  = workspaces_by_id.get(aw.workspace)   if aw.workspace else None
→ DesktopState(
    window   = WindowRef(aw.id, aw.app_id, aw.pid, aw.title),
    workspace= (ws.name if ws.named else str(ws.index)) if ws else None,   # DL-1
    output   = ws.output if ws else None)
```

Rationale (the D1 spike, notes.md §D1): Tier 1 tracks focus in-band on the `windows`
event with **no cross-family ordering dependency** — the spike proved a cross-workspace
move emits `windows` *before* `workspaces`, so a focused-workspace-primary derivation
would lag one frame (§7 D1). Tier 2 covers the only case Tier 1 can't: `active`
transiently empties to 0 mid-transition (`capture-0` frame 4) — the focused-workspace's
focused window is still correct, so the fallback yields the same window and **no flap
occurs**, purely, without prior-state. A **focused scratchpad window** (`workspace: ""`)
→ `WindowRef` present, `workspace`/`output` = `None` (best-effort; scratchpad is a
non-goal concept — DL-3). Any missing link → that field `None` (matches `DesktopState`
optionality).

### 5.3 Data, State & Ownership

- `UmbrielProjection` is **adapter-private**, owned by the session, rebuilt from scratch
  on every (re)connect from the fresh subscribe burst — never carried across a
  disconnect.
- `UmbrielWindow`/`UmbrielWorkspace` never escape `compositor/umbriel/`; only the neutral
  `DesktopState` crosses the boundary.
- Store/schema unchanged: `encode(obs, "umbriel")` → `raw/desktop-DAY.jsonl` +
  `current/desktop.json`. `producer="umbriel"` is the only new value.

### 5.4 Lifecycle, Operations & Dynamics

- **Connect**: `frames()` resolves the socket, subscribes, streams.
  `UmbrielClient.session()` is the async ctx-mgr `run_watcher` drives.
- **Initial burst → snapshot (D2).** The session runs a two-mode machine. The spike
  confirmed subscribe emits a full `windows` snapshot then a full `workspaces` snapshot
  immediately on connect — but **ordering is not guaranteed** (a `windows` event can
  precede the first `workspaces`; `capture-1` shows windows-before-workspaces on every
  transition). So:
  - *Burst mode*: buffer `apply()` until `burst_complete` (both families seen once),
    then emit the snapshot. Waiting for both is exactly what Tier-2 focus and the
    workspace→output join need; it is deterministic and testable.
  - **An empty/no-focus snapshot is valid** (`DesktopState()` when no window resolves) —
    keeps INV-U2 on an idle desktop.
  - EOF during burst mode (only one family seen) → generator returns having yielded
    nothing → partial burst discarded; `run_watcher` emits `compositor_disconnected`.
- **Live deltas → diff emission (D10)**: in live mode, after each event compute
  `to_state()` and emit the neutral event named by the highest-precedence changed field
  — `workspace_focus` on workspace/output change, else `window_focus` on focused-window
  change, else `window_title` on title change — carrying the full new state. A `windows`
  snapshot that changes only geometry (move/resize) emits nothing. A cross-workspace
  switch changes both workspace and window; one `workspace_focus` closes/opens the
  segment correctly (the deriver rekeys from the observation's `DesktopState`).
- **Coalescing**: umbriel drops identical consecutive payloads itself, so a re-emitted
  identical `windows` snapshot never reaches us; the diff layer is defence in depth.
- **Detection (D4-local)** — `detect.py`: add `umbriel` → `_umbriel_client()` and an
  `_probe_umbriel` (resolve socket, connect, send subscribe, read one framed line under
  the bounded timeout, close). `_auto_select` gains a third probe. **Ordering:** probe
  the reachable one; with a single live compositor this is unambiguous. Tie policy
  (multiple sockets set + reachable) stated in D5. Add `"umbriel"` to the
  `--compositor` `choices` in `desktop_watcher/__main__.py`.
- **Disconnect/reconnect (D3c)**: EOF/error → `run_watcher` emits
  `compositor_disconnected`, backs off, reconnects; the fresh session's snapshot-first
  stream gives the deriver a matching close/reopen. Handled by SL-002, unchanged.

### 5.5 Invariants, Assumptions & Edge Cases

- **INV-U1** — `UmbrielProjection.apply` is total and pure: unknown event family or
  field → return an equal/updated projection, never raise.
- **INV-U2** — the session's first yielded observation is always `snapshot` or nothing
  (never a delta first). The snapshot may carry an empty `DesktopState()`.
- **INV-U3** — neutral event **names** exactly match the deriver's contract (`snapshot`,
  `window_focus`, `window_title`, `workspace_focus`); a rename silently stops segments
  closing (SPEC-001 H4).
- **ASM-U1 (CONFIRMED by capture)** — `active` is the single seat-focused window:
  0-or-1 per frame across both fixtures, verified never >1. Tier-1 focus rests on this.
- **ASM-U2 (CONFIRMED by capture)** — `Workspace.output` is the DRM connector name
  (`"DP-3"`), the same space as Sway/niri `output` (SPEC-001 D4). Workspace `id` is a
  composite `"<output>:<index>"` (`"DP-3:1"`); we key `DesktopState.workspace` on the
  *name/index* (DL-1), never the composite id, so `output` is not double-counted.
- **Edge — transient `active == 0`** (`capture-0` frame 4): Tier-2 fallback yields the
  focused-workspace's focused window → no flap. **Genuine no-focus** (last window
  closed, or focus on a layer surface): focused workspace has no focused window →
  `DesktopState()` with `window=None` → correct.
- **Edge — focused scratchpad window** (`workspace: ""`): `WindowRef` surfaced,
  `workspace`/`output` = `None` (DL-3). Untested live (no capture of focusing a
  scratchpad); PHASE-01 hand-authors it.
- **Edge — multi-output** (single `DP-3` host — untested): Tier-1 is robust by
  construction (seat focus is global). Tier-2's "unique focused workspace" could be
  ambiguous if `workspaces.focused` proves per-output (>1 focused); the rule yields
  `None` (no window) in that case, firing only during the transient `active==0` window.
  If this ever manifests, the documented fallback is a session-layer prior-state hold.
  PHASE-01 notes it; not gating (single-output reality is exact).

## 6. Open Questions & Unknowns

- **OQ-1 — fixture completeness.** RESOLVED: two live host captures banked (§9,
  `capture-0` within-workspace + transient `active==0`; `capture-1` cross-workspace
  ordering) plus hand-authored edges (partial burst, reconnect, scratchpad focus,
  geometry-no-emit) the captures cannot force on demand.
- **OQ-2 (untested, low risk)** — multi-output focused-workspace cardinality (ASM/Edge
  above). Single-output host; fixtures cover the two-output *equivalence shape*.
- **OQ-3 (deferred)** — optional `panopticon-umbriel` compat entrypoint. Defer unless a
  driver needs it (SL-003 D7 stance).

## 7. Decisions, Rationale & Alternatives

- **DL-1 — workspace renders as `name` when `named`, else the index string.**
  `workspace = name if named else str(index)`. Non-null, human-legible, matches Sway/niri
  string shape; disambiguated across outputs by first-class `output` + D8's
  `(output, workspace)` key. **Never the composite `"DP-3:1"` id** (would double-count
  output in the histogram key). *Alternatives:* the composite id (double-counts output);
  `None` when unnamed (thinner signal). Mirrors niri DL-1.
- **DL-2 — burst terminator = both `windows` + `workspaces` seen once.** The spike
  proved event ordering is not guaranteed (windows can precede workspaces, incl.
  pre-burst), so a single-family or first-event terminator is unsound. Both-seen is
  deterministic; the two full snapshots are exactly what `to_state` needs. *Alternatives:*
  emit on first event (wrong — half-built projection); a timeout (non-deterministic).
- **DL-3 — umbriel-native concepts stay out of the neutral model.** Subscribe only to
  `windows` + `workspaces`; ignore `theme`/`overview`/`keyboard_layout`/`submap`. Drop
  `scratchpad`/`floating`/`content_type`/`xdg_tag`/`layout`/`urgent` — none map to
  `WindowRef`/`DesktopState`. A focused scratchpad window surfaces its `WindowRef` with
  `workspace`/`output` = `None`. *Alternative:* emit `window_urgent` from the `urgent`
  flag (as Sway does) — deferred; no consumer needs it and it widens scope. Mirrors
  niri D4/DL semantics.
- **DL-4 — focus derives from the unique `active` window, with a pure focused-workspace
  fallback (the two-tier rule); the workspace-join is NOT primary.** *Spike-driven,
  and a reversal of the pre-spike scope note.* The spike (notes.md §D1) showed: (a)
  `active` is the seat focus and updates in-band on the `windows` event, so it tracks
  within- and cross-workspace moves with no ordering lag; (b) a focused-workspace-primary
  derivation lags one frame on cross-workspace moves because `windows` precedes
  `workspaces`; (c) `active` transiently empties to 0, which the Tier-2 fallback
  (focused window on the focused workspace) covers *without* prior state, because the
  focused flags are still correct in that frame. So Tier-1 handles the common and
  cross-workspace cases; Tier-2 handles the transient-empty and layer-surface cases;
  the rule stays pure. This is the umbriel analogue of niri DL-6 (focus is derived, not
  taken from a raw focus event), but the *mechanism* differs: umbriel exposes seat focus
  directly via `active`, whereas niri had to derive it through the workspace's
  `active_window_id`. *Alternatives:* (a) workspace-join primary — rejected (one-frame
  cross-workspace lag, proven); (b) raw `active` only with a stateful hold-on-empty —
  rejected (introduces prior-state into the pure layer for no gain over Tier-2); (c)
  `active` only, emit `window=None` on every empty — rejected (flaps on `capture-0`
  frame 4).
- **DL-5 — no histogram change.** SL-003's R4 already keys `per_workspace_seconds` on
  `"output/workspace"` when `output` is present; umbriel always carries `output`, so it
  inherits correct de-conflation. SL-005 touches no segment/histogram code. *Alternative:*
  none needed.
- **Inherited (SPEC-001):** D3 (direct JSON socket, no sidecar), D4 (output
  first-class), D5 (projection adapter behind the contract), D9 (emit-time timestamps),
  D10 (diff emission), D11 (scoped id uniqueness — umbriel ids opaque, stable while
  open). Not re-litigated.

## 8. Risks & Mitigations

- **R1 — fixture fiction (docs vs live wire).** *Mitigation:* both fixtures are real
  host sessions from `umbriel 0.1.0`; hand-authored edges cross-checked against them for
  field/family shape. ASM-U1/U2 fall out of the same captures.
- **R2 — fast-moving `0.1.0` wire drift.** *Mitigation:* ignore-and-continue on unknown
  families/fields (INV-U1); fixture header stamps the captured build; no package
  dependency (stdlib `json`). A field rename (not additive) would need a re-capture —
  documented as the known fragility of an early adapter.
- **R3 — Tier-2 multi-output ambiguity** (OQ-2). *Mitigation:* single-output host is
  exact; the ambiguous branch yields `None` only during the transient `active==0`
  window; session-hold documented as the fallback if it ever manifests. Not gating.
- **R4 — no ack to validate the probe.** Unlike niri (`{"Ok":"Handled"}`), umbriel's
  subscribe has no ack. *Mitigation:* `_probe_umbriel` reads one framed line (the
  immediate burst) under the bounded timeout — a socket that connects but never streams
  fails the probe and falls through, same fail-fast property as niri's ack read.

## 9. Quality Engineering & Validation

- **Golden captures (host, outside jail — DONE at the D1 spike, 2026-09-21).** Two real
  sessions recorded from the umbriel socket (`subscribe windows,workspaces`), banked
  verbatim under `tests/fixtures/umbriel/` with `PROVENANCE.md` (build `umbriel 0.1.0`):
  - **`capture-0.ndjson`** — subscribe burst (`windows` then `workspaces` full
    snapshots) + within-workspace focus cycling, title mutation, a window open
    (`kitty`), geometry moves. **Frame 4 carries `#active==0`** — the transient case
    Tier-2 (DL-4) hinges on.
  - **`capture-1.ndjson`** — cross-workspace focus bounce; shows the
    **`windows`-before-`workspaces` ordering** (frames 3→4, 5→6, 8→9, 10→11) that
    disproves a workspace-join-primary focus model and grounds DL-4.
- **Pure projection tests** (`test_compositor_umbriel_projection.py`): snapshot replace
  (windows/workspaces), `burst_complete` gate both orders, unknown-family ignore
  (INV-U1), **two-tier focus** — Tier-1 unique `active`; Tier-2 fallback on `active==0`
  yields the focused-workspace focused window (driven from `capture-0` frame 4);
  genuine no-focus → `DesktopState()`; scratchpad focus → `workspace/output=None`;
  transitive workspace→output join; DL-1 name/index rendering.
- **Session tests** (`test_compositor_umbriel_session.py`): snapshot-first (INV-U2),
  partial-burst discard (D2), cross-workspace switch emits one `workspace_focus`
  (from `capture-1`, asserting no one-frame flap despite windows-before-workspaces),
  title-diff suppression (D10), geometry-only → no emit, transient `active==0` emits
  nothing (no flap, from `capture-0`).
- **Detection tests** (`test_compositor_detect.py`, extended): `umbriel` explicit;
  `auto` reaches umbriel when only its socket connects; three-way tie policy (D5);
  probe uses a fake socket, no live compositor.
- **Cross-compositor equivalence** (`test_compositor_equivalence.py`, extended): the
  same logical scenario (focus A→B across two workspaces on two outputs) through the
  sway, niri, **and umbriel** sessions. "Comparable" per SL-003 F-6: (a) event-name
  sequence equal; (b) `output` field matches (DRM connector names); (c) workspace-
  transition shape matches (count/order of distinct workspace values), while workspace
  *value* and `app_id` *string* may diverge. Fixtures hand-built to be structurally
  aligned → a falsifiable equality.
- **Gate**: full suite green + ruff clean (run direct in-jail; `just check` before
  commit). SL-002/SL-003 suites stay green unchanged (behaviour-preservation).
- **VH (host, non-gating)**: `panopticon-desktop --compositor auto` on the live umbriel
  host writes `current/desktop.json` with a real focused window.

## 10. Review Notes

### RV-005 — adversarial review (gpt-5.6-sol, 2026-09-21)

Ledger from the codex/gpt-5.6-sol pass, each independently verified against code
+ fixtures. **Design is NOT ready for /plan** — one blocker + two scope-breaching
majors need adjudication before revision. Status: `raised` (fixes pending decisions).

- **RV-005.1 — BLOCKER — cross-workspace focus mis-attributes the app downstream.**
  CONFIRMED end-to-end: replaying `capture-1`'s observation sequence through the real
  `segmentizer/derive.py::derive_segments` attributes **every** segment to the
  snapshot-time app (`com.mitchellh.ghostty`), though focus moved discord→emacs→…
  Root cause: `_next_focus` `workspace_focus` branch (derive.py:87-98) **retains the
  running app** and never reads the event's `app_id`; `diff_state` (niri/session.py:40)
  gives `(workspace,output)` precedence, so a cross-workspace switch (which also
  changes the window) emits `workspace_focus`, dropping the new app. **Sway escapes it**
  (emits a *second* corrective `window_focus`); niri + umbriel coalesce to one event
  and hit it — so this is a **shared latent defect niri already has**, not umbriel-only.
  Validated fix: in `diff_state`, emit `window_focus` when the focused-window identity
  changed (even if workspace also changed) — the deriver's window_focus branch rekeys
  app+workspace fully; reserve `workspace_focus` for same-window/workspace-label-only
  changes. Re-run through `derive_segments` confirms correct attribution + clean
  empty-workspace close. **Scope breach:** the fix lives in the emission/derive layer
  shared with niri (SL-005 declared model/niri untouched). → DECISION-1.
- **RV-005.2 — MAJOR — new-workspace join miss (emission coherence).** CONFIRMED
  (self-found too): a `windows` frame focusing a window whose `workspace` id is not yet
  in the latest `workspaces` snapshot (new/unknown non-empty workspace, windows-before-
  workspaces) → the join misses → `workspace`/`output`=`None` for one frame → a
  spurious `workspace_focus` then a corrected one. `to_state` is pure but reads two
  snapshots from different logical instants. Not in the captures. Fix (umbriel scope):
  split the composite `"<output>:<index>"` id when the join misses (output from prefix,
  index as workspace), OR withhold emission until the mapping lands with a bounded
  timeout. Update DL-4/§5.2, drop the §5.2 "no ordering dependency" overclaim.
- **RV-005.3 — MAJOR — DL-4 Tier-2 overclaims for unobserved focus modes.** VALID.
  The design flags multi-output (OQ-2) + scratchpad as untested, but DL-4 prose asserts
  Tier-2 "covers layer-surface, overview cases" with no capture. Gaps: multi-output
  (>1 focused workspace → Tier-2 empties during `active==0` → a false segment-close);
  layer/overview (unknown whether per-workspace `focused` persists — contradicts the
  "genuine no-focus" claim at §5.5); a focused scratchpad with `active:false` → Tier-2
  picks the tiled window; `>1 active` (multi-seat) policy unstated. Fix: capture these
  live (host access available), OR state an explicit **single-seat** assumption, define
  `>1 active` handling, and downgrade "covers" → "untested; documented fallback".
- **RV-005.4 — MAJOR — umbriel window ids violate the neutral model's declared type.**
  CONFIRMED: `model.py:28` declares `WindowRef.window_id: int | None`; every umbriel id
  is an opaque hex **string** (`"927b2d7e…"`). §5.2 passes it straight to `WindowRef`.
  Dataclass accepts it at runtime but the typed contract + `current/desktop.json` schema
  break, invalidating "model unchanged". (Note: `window_id` is NOT in the focus key —
  derive keys on app_id — so segment correctness is unaffected; the breach is the
  contract/schema.) Options: widen `window_id` to `int | str | None` (touches SL-002
  model + schema + docs) / canonicalize / drop to `None` for umbriel. → DECISION-2.
- **RV-005.5 — MAJOR — burst gate can hang on a half-burst; reconnect announced early.**
  (a) VALID: only connect + first read are `connect_timeout`-bounded; one family then a
  silent-but-open socket waits forever for the second. Also latent in niri. Fix: a
  bounded **burst-completion** timeout that raises (→ disconnect), distinct from the
  per-read timeout. (b) `runner.py:113` emits `compositor_reconnected` + resets backoff
  *before* iterating observations, and the niri/umbriel session connects lazily inside
  the generator → "reconnected" can precede the actual connect. Pre-existing runner+niri
  behaviour; note as a shared issue, likely out of SL-005 scope.
- **RV-005.6 — MINOR — socket resolution + three-way tie policy underspecified.** VALID.
  `$XDG_RUNTIME_DIR`/`$WAYLAND_DISPLAY` unset → a path containing `"None"`; need an
  actionable error. `auto` derived-socket eligibility unstated. **§5.4 says the tie
  policy is "stated in D5" — but DL-5 is the histogram decision (cross-ref bug); no
  three-way order is actually specified.** Fix: lock a total order (e.g. niri > sway >
  umbriel, or umbriel-preferred-when-live) and say whether `auto` probes the derived path.
- **RV-005.7 — MINOR — `pid:-1` XWayland sentinel surfaced as a real pid.** VALID
  (`capture-0` line 1, Spotify `pid:-1`). Fix: normalize non-positive pids to `None`
  in the projection; fixture-driven test. Likely applies to niri too.
- **RV-005.8 — MINOR — provenance + schema docs contradict the design.** VALID.
  `tests/fixtures/umbriel/PROVENANCE.md` "Absent captures" still says workspace-switch
  uncaptured + "workspace→window join" as the rule (pre-spike, contradicts DL-4 + the
  banked `capture-1`). `docs/schema.md` lists only `sway|niri` producers → "docs
  untouched" leaves the public contract false. Fix: reconcile provenance; add `umbriel`.

**Confirmed sound:** the histogram path (DL-5) — `"DP-3:1"` → `workspace="emacs",
output="DP-3"` → key `"DP-3/emacs"`; `histogram.py` needs no change. DL-2's ordering
handling (workspaces-first, one-family-then-EOF) is safe.

**Two decisions gate the revision** (both breach the "additive, model/niri untouched"
boundary):
- **DECISION-1 (RV-005.1):** where the app-attribution fix lands — (a) promote the
  diff/emission logic to shared compositor code + fix once (touches done niri + its
  behaviour-preservation suite, which may encode the bug); (b) fix umbriel's own clone
  only + file niri separately (tight boundary, but duplicated logic + niri stays buggy —
  violates no-parallel-implementation); (c) split the shared derive/diff correctness fix
  into its own prerequisite slice that SL-005 `needs`.
- **DECISION-2 (RV-005.4):** window-id type — widen the neutral `WindowRef.window_id`
  to `int | str | None` (+ schema/docs) vs canonicalize vs drop to `None` for umbriel.

### D1 spike (2026-09-21) — the focus-model gate

The live spike on `umbriel 0.1.0` (notes.md §D1) settled DL-4 before design lock,
reversing the pre-spike scope assumption (which favoured the workspace-join). What it
proved: `focused` is per-workspace (multi-true, not a global signal); `active` is the
seat focus (0-or-1, verified) but transiently empties; cross-workspace moves emit
`windows` before `workspaces`. → the two-tier pure rule (DL-4). Both captures banked as
the design→plan fixtures.

### Phase shape (provisional — finalised at /plan)

1. **PHASE-01 — Protocol + pure projection.** `umbriel/protocol.py` (socket resolve +
   subscribe framing) and `umbriel/projection.py` (snapshot replace + two-tier
   `to_state`). Green against both captures + hand-authored edges (scratchpad focus,
   partial burst).
2. **PHASE-02 — Session + normalization + equivalence.** `umbriel/session.py`
   (burst-gate, diff emission), snapshot-first stream, cross-compositor equivalence.
3. **PHASE-03 — Live wire-up.** `detect.py` three-way probe + `--compositor` choices.
   `--compositor auto` runs umbriel live end-to-end.
