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
  (`protocol.py` framing, `projection.py` accumulator, `session.py` burst-gate).
- **Shared diff** (`compositor/diff.py`, landed by ISS-001): the pure
  `diff_state(prior, new) -> DesktopObservation | None` emission core, promoted out of
  niri so niri + umbriel share one implementation and precedence (DL-7).
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
- **Behaviour-preservation gate**, with **two scoped, deliberate exceptions** (both
  adjudicated in the RV-005 review, §10): (1) **ISS-001** promoted `diff_state` to a
  shared `compositor/diff.py` and corrected its emission precedence — a documented
  *improvement* to niri, so three SL-003 tests were updated to the corrected names (the
  gate is *reconciled*, not silently broken); (2) **DL-6** widens the SL-002-owned
  `WindowRef.window_id` type (`int|str|None`) — a type-only widen that leaves the
  SL-002/SL-003 suites green. Otherwise `histogram.py`, the event names, and the sway
  adapter are untouched; outside `compositor/umbriel/` only `detect.py` (probe),
  `model.py` (DL-6), `docs/schema.md`, and the CLI `choices` change.
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
                 burst-completion gate (D2), diff emission via the SHARED
                 compositor/diff.py::diff_state (DL-7 / ISS-001 — one impl for
                 niri + umbriel). Snapshot-first observation stream.
```

The diff/emission core is **not** re-implemented here: `session.py` calls
`panopticon.compositor.diff.diff_state` (promoted out of niri by ISS-001, landed).
Umbriel adds only the projection + the impure socket shell around that shared core.

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
    @property
    def focus_coherent(self) -> bool: ...   # focus fully resolvable (RV-005.2); see §5.2
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
# Derive (pure, best-effort; the session decides emission timing — see coherence hold):
if aw is None:  → DesktopState()                        # genuine no-focus
ws  = workspaces_by_id.get(aw.workspace)   if aw.workspace else None
label, output = _locate(aw.workspace, ws)
→ DesktopState(
    window   = WindowRef(aw.id, aw.app_id, _pid(aw.pid), aw.title),   # id: str (DL-6)
    workspace= label,                                   # DL-1
    output   = output)

# _pid — XWayland surfaces carry pid:-1 (capture-0 line 1, Spotify); a sentinel, not a
#        real pid → normalise non-positive to None (RV-005.7 / DL-9). type-check excludes
#        bool (a subclass of int) so a stray True never reads as pid 1.
def _pid(p): return p if type(p) is int and p > 0 else None

# _locate — window→workspace→output. The workspace id is the composite
#   "<output>:<opaque-id>" (e.g. "DP-3:17"); the SUFFIX is an internal id, NOT the
#   display index — capture-0 L2: id "DP-3:17" has index 2 / name "2" (DL-1/ASM-U2). So
#   the label comes ONLY from the resolved workspaces entry, never the suffix. The PREFIX
#   is the output (DRM connector, no colons) and is reliable even before the entry lands.
def _locate(ws_id, ws):
    if ws is not None:                       # resolved: label from the entry (DL-1)
        return (ws.name if ws.named else str(ws.index)), ws.output
    if ws_id == "" or ws_id is None:         # scratchpad / no workspace
        return None, None
    return None, ws_id.split(":", 1)[0] or None   # UNRESOLVED (new ws, entry not yet in
                                             # map): output=prefix; label unknown → None.
                                             # focus_coherent is False → LIVE mode holds
                                             # (snapshot/burst emits this best-effort).

# focus_coherent — is the current focus fully resolvable? The session withholds emission
#   until it is (bounded — see §5.4 coherence hold). False iff a window is focused on a
#   non-empty workspace id absent from the workspaces map (the windows-before-workspaces
#   new-workspace case). True for no-focus, scratchpad (""), and resolved workspaces.
@property
def focus_coherent(self) -> bool: ...
```

Rationale (the D1 spike, notes.md §D1): Tier 1 tracks the focused-window *identity*
in-band on the `windows` event with **no cross-family ordering dependency for focus** —
the spike proved a cross-workspace move emits `windows` *before* `workspaces`, so a
focused-workspace-*primary* derivation would lag one frame on *which window* is focused
(§7 DL-4). The workspace→output **label** join reads the `workspaces` map, which the
projection *retains* between events — so a focus onto a **pre-existing** workspace (the
whole `capture-1` bounce, and every ordinary cross-workspace move) resolves immediately;
there is no miss. The join misses **only** for a genuinely *new* workspace whose `windows`
event precedes its first `workspaces` event; the id suffix cannot supply its label
(it is an opaque id, not the index), so the session **holds** the transition until the
entry lands rather than fabricate one (§5.4 coherence hold, RV-005.2). Tier 2 covers the
only *focus* case Tier 1 can't: `active`
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
  - **Burst-completion deadline (RV-005.5a).** `connect_timeout` bounds only connect +
    the first read; a socket that sends one family then goes silent-but-open would wait
    for the second forever. So burst mode carries a distinct `burst_timeout` (default
    the same 2.0 s) measured from connect: elapsing before `burst_complete` raises →
    `run_watcher` turns it into a `compositor_disconnected` + backoff, rather than a
    wedged session. (The equivalent hang is latent in niri; the fix rides the shared
    session shape where practical, else is umbriel-local — noted for the niri backlog.)
- **Coherence hold (RV-005.2).** Applies to **live mode only** — the burst/snapshot emits
  best-effort (a full snapshot is as coherent as umbriel gets; no hold, so no reconnect
  loop). In live mode, after `apply(event)`, if `proj.focus_coherent` is `False` — a
  window is focused on a non-empty workspace id not yet in the workspaces map (a *new*
  workspace whose `windows` event led its `workspaces` event) — the session **withholds**:
  it neither emits nor advances its `prior` baseline, and folds the next event. The
  following `workspaces` frame lands the entry → coherent → the accumulated change emits as
  a **single precedence-correct observation**: `window_focus` when the focused-window
  identity changed, or `workspace_focus` when the *same* window merely moved onto the new
  workspace (per DL-7 — never a fabricated label, no None→label flap either way).
- **Coherence timeout → disconnect/reburst (RV-005.2, fail-safe).** Bounded by a
  `coherence_timeout` (same default as the burst deadline). If coherence never arrives, the
  session does **not** emit a `workspace=None` live observation — that would mis-derive
  (a `window_focus(ws=None)` reads as defocus and the later `workspace_focus` cannot reopen
  a segment from `running=None`; a same-window `workspace_focus` would misattribute the
  interval). Instead it **raises → `run_watcher` emits `compositor_disconnected`, backs
  off, and reconnects**, re-seeding a fresh consistent snapshot (deriver closes the running
  segment, then reopens correctly). Same recovery path as the burst-completion timeout; no
  incoherent live observation ever escapes. The common cross-workspace move (pre-existing
  target) is always coherent → no hold, no timeout. This generalises the burst gate's
  "don't emit an incoherent intermediate" to live mode.
- **Live deltas → diff emission (D10, precedence per DL-7/ISS-001)**: once coherent, in
  live mode compute `to_state()` and hand `(prior, new)` to the shared
  `compositor/diff.py::diff_state`, which names the observation by the highest-precedence
  changed field — a **focused-window-identity change (incl. focus→none) →
  `window_focus`**, else a same-window workspace/output change → `workspace_focus`, else
  a title change → `window_title` — carrying the full new state. A `windows` snapshot
  that changes only geometry (move/resize) emits nothing. A **cross-workspace switch
  changes both the window and the workspace**, so it emits one `window_focus`: the
  deriver rekeys app+workspace from the observation's `DesktopState`, attributing the
  segment to the newly-focused app (this is exactly the mis-attribution ISS-001 fixed —
  the umbriel single-full-snapshot case had no corrective follow-up event). Only a focus
  that stays on the *same* window while its workspace label changes emits
  `workspace_focus`.
- **Coalescing**: umbriel drops identical consecutive payloads itself, so a re-emitted
  identical `windows` snapshot never reaches us; the diff layer is defence in depth.
- **Detection (D4-local)** — `detect.py`: add `umbriel` → `_umbriel_client()` and an
  `_probe_umbriel` (resolve socket, connect, send subscribe, read one framed line under
  the bounded timeout, close). `_auto_select` gains a third probe. **Ordering &
  resolution (DL-8):** probe in a fixed total order `niri > sway > umbriel`, first
  reachable wins; with a single live compositor this is unambiguous, and the order only
  breaks a genuine multi-socket tie. Socket resolution for the probe: use
  `$UMBRIEL_SOCKET` if set, else the derived `$XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock`
  **only when both env vars are present** — if either is unset the derived path is
  ineligible (the auto-probe skips umbriel rather than fabricating a `.../umbriel-None.sock`);
  an *explicit* `--compositor umbriel` with unresolvable env raises an actionable error.
  Add `"umbriel"` to the `--compositor` `choices` in `desktop_watcher/__main__.py`.
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
  **`>1 active` policy (unobserved):** Tier-1 takes the *unique* active window, so
  `>1 active` yields no Tier-1 pick and falls through to Tier-2 (or `DesktopState()`) —
  a defined, non-crashing degrade, not a crash or an arbitrary pick.
- **ASM-U3 (ASSUMED — single-seat)** — one wl_seat, so seat focus is a single global
  signal. Not exercised (single-seat host); a multi-seat umbriel could carry `>1 active`
  (one per seat), handled by the ASM-U1 policy above. Stated, not gating.
- **ASM-U2 (CONFIRMED by capture)** — `Workspace.output` is the DRM connector name
  (`"DP-3"`), the same space as Sway/niri `output` (SPEC-001 D4). Workspace `id` is a
  composite `"<output>:<opaque-id>"` — the suffix is an **internal id, NOT the display
  index**: `capture-0` L2 has id `"DP-3:17"` with `index=2`, `name="2"`, and id `"DP-3:1"`
  with `index=1`, `name="emacs"`. So `DesktopState.workspace` is keyed on the entry's
  *name/index* (DL-1), never the id suffix; the id **prefix** is a reliable `output`
  source (connectors carry no colon) used only as the coherence-hold fallback. `output`
  is thus never double-counted, and the suffix never leaks as a label.
- **Edge — transient `active == 0`** (`capture-0` frame 4): Tier-2 fallback yields the
  focused-workspace's focused window → no flap. **Genuine no-focus** (last window
  closed): focused workspace has no focused window → `DesktopState()` with `window=None`
  → correct. **Layer-surface / overview focus (UNTESTED, RV-005.3):** it is *unconfirmed*
  whether per-workspace `focused` persists on the last tiled window while focus rests on
  a layer surface. If it persists, Tier-2 keeps attributing to that tiled window rather
  than closing — **an over-count bounded only by how long focus rests on the layer
  surface** (seconds for a launcher/overview; unbounded for a persistent layer shell, so
  *not* generally bounded — stated honestly, not as "small"). If it clears, we get the
  correct `DesktopState()`. **Phase gate (RV-005.3):** PHASE-01 attempts a live
  layer-surface capture (host access) to settle whether `focused` persists; **if that
  capture is inconclusive or skipped, the over-count stands as an accepted limitation of
  the umbriel adapter** (documented in schema/notes), not a silent gap — no design
  invariant depends on it.
- **Edge — scratchpad with `active:false`** (RV-005.3): a scratchpad window
  (`workspace: ""`) that is not the seat-active window is not picked by Tier-1; Tier-2
  joins on the focused *workspace*, and a scratchpad has no workspace, so Tier-2 does not
  select it either → it never spuriously becomes focus. A scratchpad window that **is**
  seat-active surfaces via Tier-1 with `workspace/output=None` (DL-3). Untested live;
  PHASE-01 hand-authors both from the capture vocabulary.
- **Edge — `pid` sentinel** (`capture-0` line 1, Spotify `pid:-1`): XWayland surfaces
  carry `pid:-1`; `_pid` normalises non-positive → `None` so no `-1` reaches the schema
  (RV-005.7). Fixture-driven; likely applies to niri too (noted for its backlog).
- **Edge — join miss (new workspace, windows-before-workspaces)** (RV-005.2): the
  projection retains the last workspaces snapshot, so a focus onto any **pre-existing**
  workspace resolves immediately (no miss — the entire `capture-1` bounce). The miss
  arises **only** for a *genuinely new* workspace whose `windows` event precedes its first
  `workspaces` event; the id suffix is opaque (not the index) so no label can be
  fabricated. `focus_coherent` is `False` → the **session coherence-holds** (§5.4) until
  the `workspaces` entry lands, then emits one precedence-correct observation
  (`window_focus` / `workspace_focus` per DL-7). If the entry never lands within
  `coherence_timeout`, the session **raises → disconnect/reburst** (fail-safe; no
  `workspace=None` live observation escapes). Hand-authored (unobserved in the captures,
  which only exercise pre-existing targets).
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
  cross-workspace cases; Tier-2 handles the **transient-empty case (proven,
  `capture-0` frame 4)**. The **layer-surface / overview** case is *untested* — whether
  per-workspace `focused` persists there is unconfirmed (§5.5 edge, RV-005.3); Tier-2's
  behaviour is bounded either way but not asserted as "covered" until PHASE-01 captures
  it. The rule stays pure. This is the umbriel analogue of niri DL-6 (focus is derived, not
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
- **DL-6 — widen `WindowRef.window_id` to `int | str | None`** (DECISION-2, david).
  Every umbriel id is an opaque hex **string** (`"927b2d7e…"`); the model declared
  `int | None` (RV-005.4). Widen the neutral field rather than coerce ids to ints (lossy,
  fragile) or stringify every producer's id (churns sway/niri + the schema). `window_id`
  is **not** in the focus key (the deriver keys on `app_id`), so segment correctness is
  unaffected — the breach was purely the typed contract + `current/desktop.json` schema.
  A scoped, deliberate change to the SL-002-owned model, folded into SL-005 (executed in
  PHASE-01 with `docs/schema.md` + identity tests); future-proofs other string-id
  compositors. *Alternatives:* coerce/hash to int (lossy, collision risk); leave `int`
  and lie in the types (rejected — invalidates "model unchanged" dishonestly).
- **DL-7 — focus-emission precedence + shared `diff_state` (ISS-001, LANDED).**
  Emission uses the shared `compositor/diff.py::diff_state`, whose precedence is a
  **focused-window-identity change (incl. focus→none) → `window_focus`** ahead of a
  same-window location change → `workspace_focus`. Umbriel's full-snapshot-per-event
  means a cross-workspace switch is a single combined-change event with no corrective
  follow-up; the old workspace-first precedence dropped the new app (mis-attributing the
  whole segment to the prior app). Fixed once, shared by niri + umbriel (no parallel
  emission logic), before SL-005 planning. See §10 RV-005.1 / ISS-001. *Alternative:*
  an umbriel-local diff copy — rejected (parallel implementation; the defect is generic).
- **DL-8 — probe order `niri > sway > umbriel`; derived socket needs both env vars.**
  `_auto_select` probes in that fixed total order, first reachable wins (the order only
  decides a genuine multi-socket tie, unusual in practice). The derived socket path
  (`$XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock`) is eligible for the auto-probe only
  when **both** env vars are set; otherwise auto skips umbriel rather than fabricate a
  `.../umbriel-None.sock`. An *explicit* `--compositor umbriel` with unresolvable env
  raises an actionable error (RV-005.6). *Alternatives:* umbriel-preferred (no reason to
  favour the newest); probe the `"None"` path (produces a confusing connect error).
- **DL-9 — non-positive `pid` → `None`.** XWayland surfaces report `pid:-1` (a sentinel,
  `capture-0` line 1); the projection normalises any non-positive/non-int pid to `None`
  so no sentinel reaches the neutral model or schema (RV-005.7). Likely applies to niri
  too — noted for its backlog, out of SL-005 scope. *Alternative:* surface `-1` verbatim
  (leaks a fake pid downstream).
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
  `>1 active` → no Tier-1 pick, falls through (ASM-U1 policy); genuine no-focus →
  `DesktopState()`; scratchpad focus → `workspace/output=None`; transitive
  workspace→output join; **new-workspace join miss → `focus_coherent` False** (label not
  fabricated from the id suffix), with the id **prefix** as the output fallback
  (DL-4/RV-005.2); **`pid:-1` → `None`**, and `pid:True`/`False` → `None` (DL-9, bool
  excluded, from `capture-0` line 1); DL-1 name/index rendering (id suffix ≠ index —
  `capture-0` L2).
- **Session tests** (`test_compositor_umbriel_session.py`): snapshot-first (INV-U2),
  partial-burst discard (D2), **burst-completion timeout raises** on a one-family-then-
  silent socket (RV-005.5a), **cross-workspace switch emits one `window_focus`** with the
  new app attributed (from `capture-1`; DL-7/ISS-001 — asserting no one-frame flap and no
  app mis-attribution despite windows-before-workspaces), **coherence hold — a new-
  workspace windows-before-workspaces sequence emits a single precedence-correct
  observation with the resolved label (no None→label or suffix→label flap); and the
  `coherence_timeout` path raises → disconnect/reburst (no `workspace=None` live emit)**
  (RV-005.2), title-diff suppression (D10), geometry-only → no emit, transient `active==0`
  emits nothing (no flap, from `capture-0`).
  (The shared `diff_state` + deriver attribution itself is regression-locked in
  `test_diff_derive_attribution.py`, landed with ISS-001.)
- **Detection tests** (`test_compositor_detect.py`, extended): `umbriel` explicit;
  `auto` reaches umbriel when only its socket connects; three-way tie policy (D5);
  probe uses a fake socket, no live compositor.
- **Cross-compositor equivalence** (`test_compositor_equivalence.py`, extended): the
  same logical scenario (focus A→B across two workspaces on two outputs) through the
  sway, niri, **and umbriel** sessions. "Comparable" per SL-003 F-6, as revised by
  ISS-001: (a) **snapshot-first on all three, and the same landing** — final focus on B,
  landing event `window_focus`; (b) `output` field matches (DRM connector names);
  (c) workspace-transition shape matches (count/order of distinct workspace values),
  while workspace *value* and `app_id` *string* may diverge. The **intermediate** event
  name may legitimately differ by adapter (niri nulls the window through an empty target
  → `window_focus`; sway retains the prior window → `workspace_focus`) — a documented
  adapter difference the ISS-001 precedence surfaced, asserted per-adapter, not forced
  equal. Umbriel's single-event switch lands directly as `window_focus` (no intermediate).
  Fixtures hand-built to be structurally aligned → a falsifiable comparison.
- **Gate**: full suite green + ruff clean (run direct in-jail; `just check` before
  commit). SL-002/SL-003 suites stay green unchanged (behaviour-preservation).
- **VH (host, non-gating)**: `panopticon-desktop --compositor auto` on the live umbriel
  host writes `current/desktop.json` with a real focused window.

## 10. Review Notes

### RV-005 — adversarial review (gpt-5.6-sol, 2026-09-21)

Ledger from the codex/gpt-5.6-sol pass, each independently verified against code
+ fixtures. **Status: blocker (ISS-001) LANDED; design revised three times across two
confirming re-reviews.** 2nd pass: RV-005.1/.4/.6/.7/.8 RESOLVED, first RV-005.2 fix
rejected (read the composite-id suffix as the display index — `capture-0` L2 disproves
it: `"DP-3:17"` has `index=2`). 3rd pass (narrow, coherence-hold surface only): ASM-U2
+ `_locate` SOUND, RV-005.3 wording SOUND, but caught a **BLOCKER** in the coherence
timeout fail-open (mis-derives) + a `window_focus` overclaim — both fixed this revision
(timeout → disconnect/reburst; "one precedence-correct observation"). Per-item
disposition in "Revision — applied".

- **RV-005.1 — BLOCKER — cross-workspace focus mis-attributes the app downstream.**
  CONFIRMED end-to-end: replaying `capture-1`'s observation sequence through the real
  `segmentizer/derive.py::derive_segments` attributes **every** segment to the
  snapshot-time app (`com.mitchellh.ghostty`), though focus moved discord→emacs→…
  Root cause: `_next_focus` `workspace_focus` branch (derive.py:87-98) **retains the
  running app** and never reads the event's `app_id`; `diff_state` (niri/session.py:40)
  gives `(workspace,output)` precedence, so a transition that changes *both* workspace
  and window emits a single `workspace_focus`, dropping the new app.
  **Granularity is the discriminator** (refined post-review): **sway** emits a
  corrective `window_focus` after `workspace_focus` (two i3ipc events); **niri**
  decomposes a switch into `WorkspaceActivated` (→ `workspace_focus`, empty intermediate)
  then `WorkspaceActiveWindowChanged` (→ `window_focus`) — so niri's bug is **latent**
  (bites only when switching to an already-populated workspace in one event);
  **umbriel** delivers a full snapshot per event, so a cross-workspace switch is
  **always** one collapsed `workspace_focus` with no corrective follow-up → always
  mis-attributes. Validated fix: emit `window_focus` when the focused-window identity
  changed (even under a simultaneous workspace/output change) — the deriver's
  window_focus branch rekeys app+workspace fully and closes cleanly on window→None;
  reserve `workspace_focus` for same-window workspace-label-only changes. Re-run through
  `derive_segments` confirms correct attribution + clean empty-workspace close.
  **RESOLUTION (DECISION-1, david):** tractable (~3 LOC + 3 test updates) → tracked as
  **ISS-001** (`SL-005 needs ISS-001`); promote `diff_state` to a shared compositor
  module, fix once for niri + umbriel (DRY), update the 3 niri/equivalence tests that
  encode the old precedence (a deliberate, documented improvement — the behaviour-
  preservation gate is reconciled, not silently broken). Worked as a prerequisite
  before SL-005 planning.
- **RV-005.2 — MAJOR — new-workspace join miss (emission coherence).** CONFIRMED
  (self-found too): a `windows` frame focusing a window whose `workspace` id is not yet
  in the latest `workspaces` snapshot (new/unknown non-empty workspace, windows-before-
  workspaces) → the join misses → `workspace`/`output`=`None` for one frame → a
  spurious `workspace_focus` then a corrected one. `to_state` is pure but reads two
  snapshots from different logical instants. Not in the captures.
  **First fix REJECTED (re-review):** splitting `"<output>:<index>"` for an index label
  was based on a false premise — the id suffix is an **opaque internal id, not the display
  index** (`capture-0` L2: id `"DP-3:17"` → `index=2`/`name="2"`; `"DP-3:1"` →
  `name="emacs"`). Returning the suffix as the label is both a wrong value and a guaranteed
  flap (label refines suffix→real-name next frame → `workspace_focus` → segment split) —
  the exact defect it claimed to fix.
  **RESOLUTION (second revision):** the projection **retains** the last workspaces
  snapshot, so pre-existing targets never miss (the whole `capture-1` bounce is coherent);
  the miss is confined to a *genuinely new* workspace. For that, a **session coherence
  hold** (§5.4, `focus_coherent`): `to_state` never fabricates a label (output from the
  reliable id prefix, `workspace=None` when unresolved); the session withholds the
  transition until the `workspaces` entry lands → one clean `window_focus`; bounded by a
  `coherence_timeout` that fails open. Also scopes the §5.2 "no ordering dependency" claim
  to focus-*identity*.
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
  contract/schema.) **RESOLUTION (DECISION-2, david): widen `WindowRef.window_id` to
  `int | str | None`** (+ `docs/schema.md` + any identity annotations/tests). Honest,
  low-risk (not in the focus key), future-proofs other string-id compositors. This is a
  scoped, deliberate change to the SL-002-owned neutral model — folded into SL-005 (or
  ISS-001's shared touch), not a non-goal violation left implicit.
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

**Both scope decisions RESOLVED (david, 2026-09-21):**
- **DECISION-1 (RV-005.1):** shared `diff_state` precedence fix, tracked as **ISS-001**,
  worked as a prerequisite (`SL-005 needs ISS-001`); promote to shared, fix niri +
  umbriel once. See RV-005.1 resolution above.
- **DECISION-2 (RV-005.4):** widen `WindowRef.window_id` to `int | str | None`. See
  RV-005.4 resolution above.

**Revision — applied (2026-09-21; second revision after the confirming re-review).**
Per-item disposition:
- **RV-005.1** — LANDED as **ISS-001** (commits c0ab29a/365e4f3, status `resolved·fixed`).
  Shared `compositor/diff.py::diff_state`, window-identity-wins precedence; niri + umbriel
  share it. Design: DL-7, §5.1, §5.4 emission rewrite. **Re-review: RESOLVED.**
- **RV-005.2** (join miss) — **first fix (id-split) REJECTED** by the 2nd pass (false
  premise: suffix ≠ index). **Second fix (coherence hold) refined by the 3rd (narrow)
  pass**, which caught two things: (i) "one `window_focus`" overclaimed — a *same-window*
  move onto the new workspace is correctly `workspace_focus` (DL-7), so the guarantee is
  "one precedence-correct observation"; (ii) **BLOCKER** — the original fail-open ("emit
  best-effort `workspace=None` and resume") mis-derives (a `window_focus(ws=None)` reads
  as defocus and the later `workspace_focus` can't reopen from `running=None`; a
  same-window `workspace_focus` misattributes the interval). **Corrected:** the
  `coherence_timeout` now **raises → disconnect/reburst** (fail-safe, same path as the
  burst timeout — no incoherent live observation escapes); burst/snapshot never holds
  (emits best-effort), ruling out a reconnect loop. Live-only hold via `focus_coherent`;
  `to_state` never fabricates a label (output from the reliable id prefix). §5.2/§5.4/§5.5,
  ASM-U2 corrected; PROVENANCE + slice scope de-staled (`output:<opaque-id>`).
- **RV-005.3** (Tier-2 overclaim) — DL-4 + §5.5 downgraded layer/overview to *untested*;
  **ASM-U3 single-seat** + **`>1 active` policy** (ASM-U1) added; **scratchpad
  `active:false`** edge settled (neither tier picks it); layer-surface over-count restated
  honestly as **not generally bounded**, with an explicit **PHASE-01 capture-or-accept
  phase gate** (re-review PARTIAL → addressed).
- **RV-005.4** — DECISION-2 → **DL-6** widen `WindowRef.window_id` to `int|str|None`
  (executed PHASE-01 with `docs/schema.md` + tests; `diff._identity` already typed for it).
- **RV-005.5a** (burst hang) — bounded **burst-completion timeout** (§5.4, DL-8-adjacent);
  session test added (§9). **Re-review: RESOLVED.** **RV-005.5b** (runner announces
  `compositor_reconnected` + resets exponential backoff *before* the lazy connect → false
  reconnects and a backoff that resets to the initial delay on repeated connect failures)
  — **explicitly DEFERRED, not resolved**: a pre-existing shared runner+niri concern,
  scoped out of SL-005 as a backlog candidate (below). Re-review flagged that "BL-candidate"
  is a disposition, not a fix — acknowledged as such here.
- **RV-005.6** — **DL-8** (probe order `niri>sway>umbriel`; derived socket needs both env
  vars; explicit-umbriel unresolvable-env error). Fixes the dead "stated in D5" cross-ref.
  **Re-review: RESOLVED.**
- **RV-005.7** — **DL-9** non-positive `pid → None`, **`type(p) is int`** excluding `bool`
  (re-review minor: `isinstance` would accept `True` as pid 1); §5.2 `_pid`, §5.5 edge,
  §9 test. **Re-review: RESOLVED.**
- **RV-005.8** — PROVENANCE.md "Absent captures" **reconciled now** to DL-4 + the banked
  `capture-1` (the fixtures exist, so the stale focus-model claim was actively wrong).
  `docs/schema.md` is **deferred to execution** on purpose: the `window_id` type note
  lands with the DL-6 widening (PHASE-01) and the `umbriel` producer entry with the
  wire-up (PHASE-03) — adding a producer the code doesn't yet emit would make the public
  contract claim a source that isn't live. Tracked as a PHASE deliverable, not a doc left
  false.

**Backlog candidates surfaced (not SL-005, flagged for david):**
- **Sway transient micro-segment.** On a two-step cross-output switch, sway reports the
  *prior* window while the workspace refocuses (`workspace_focus` with window A), leaving a
  transient A-on-ws2 micro-segment in the derived stream. Pre-existing, orthogonal to
  ISS-001 (sway keeps identity → its emission is byte-identical before/after the fix).
  Documented in the equivalence-test docstring + ISS-001 body.
- **RV-005.5b runner reconnect ordering** — `run_watcher` emits `compositor_reconnected`
  + resets backoff before the session's lazy connect, so "reconnected" can precede the
  actual connect. Shared runner+niri concern.

### D1 spike (2026-09-21) — the focus-model gate

The live spike on `umbriel 0.1.0` (notes.md §D1) settled DL-4 before design lock,
reversing the pre-spike scope assumption (which favoured the workspace-join). What it
proved: `focused` is per-workspace (multi-true, not a global signal); `active` is the
seat focus (0-or-1, verified) but transiently empties; cross-workspace moves emit
`windows` before `workspaces`. → the two-tier pure rule (DL-4). Both captures banked as
the design→plan fixtures.

### Phase shape (provisional — finalised at /plan)

1. **PHASE-01 — Neutral model widening + protocol + pure projection.** DL-6: widen
   `WindowRef.window_id` → `int|str|None` in `compositor/model.py` + the `window_id`
   type note in `docs/schema.md` (SL-002/SL-003 suites stay green — a type-only widen).
   `umbriel/protocol.py` (socket resolve + subscribe framing) and `umbriel/projection.py`
   (snapshot replace + two-tier `to_state`, `_locate` output-from-prefix / no-fabricated-
   label, `focus_coherent`, `_pid` normalisation). Green against both captures +
   hand-authored edges (scratchpad focus/active, partial burst, new-workspace join miss,
   `pid:-1`). If host access allows, attempt a live layer-surface capture (RV-005.3 gate);
   else record the accepted limitation.
2. **PHASE-02 — Session + normalization + equivalence.** `umbriel/session.py` (burst-gate
   + **burst-completion timeout** + **live coherence hold** with `coherence_timeout`, diff
   emission via the shared `diff_state`), snapshot-first stream, cross-compositor
   equivalence (umbriel arm), literal `capture-1` replay → observations →
   `derive_segments` attribution.
3. **PHASE-03 — Live wire-up.** `detect.py` three-way probe (DL-8 order + derived-socket
   eligibility) + `--compositor` choices + the `umbriel` producer entry in
   `docs/schema.md`. `--compositor auto` runs umbriel live end-to-end.
