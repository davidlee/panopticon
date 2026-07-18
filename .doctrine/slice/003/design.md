# Design SL-003: Niri adapter

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. Decisions inherited from SPEC-001 are cited as SPEC-001 Dn;
     decisions local to this slice are DL-n. -->

## 1. Design Problem

Add **Niri** as a second peer adapter behind the `CompositorSession` contract
SL-002 defined, and — because the user now runs Niri while the deployed Sway
watcher is dormant (`mem.fact.panopticon.niri-live-sway-dead`) — **restore live
desktop-attention data end-to-end**. Unlike SL-002 (a behaviour-preserving
refactor), this is a greenfield external-protocol adapter: a different risk
profile whose only in-jail verification surface is fixtures.

Delivery boundary (locked this design): the Niri adapter **plus** the live
wire-up needed for data to flow — completing `detect.py`'s D7 resolution and
widening `histogram.py` (R4) so Niri's per-output workspaces do not conflate.
SATAN's cross-repo semantic coordination is **out** (SL-004).

## 2. Current State

SL-002 shipped the neutral core and Sway adapter:

- **Contract** (`compositor/model.py`): `WindowRef`, `DesktopState`,
  `DesktopObservation`; `CompositorSession.observations() -> AsyncIterator`
  (snapshot-first, the pull→push inversion); `CompositorClient{producer, session()}`.
- **Runner** (`compositor/runner.py`): `process_session` (encode + store each
  observation, no state threading) and `run_watcher` (reconnect/backoff; emits
  neutral `compositor_disconnected`/`compositor_reconnected`; the fresh session
  supplies the post-reconnect snapshot).
- **Encoder** (`compositor/events.py`): `encode(obs, producer)` — the sole
  `source`/`producer` injector (INV-2).
- **Sway adapter** (`compositor/sway/{project,session,_i3ipc}.py`): a live
  tree-projection session mirroring the shape this slice reuses for Niri.
- **Detection** (`compositor/detect.py`): Sway path live; `niri` and
  `auto`-without-Sway raise `NotImplementedError` — an explicit SL-003 seam. The
  `auto` Sway check is a `SWAYSOCK`-presence stand-in (RV-001 F-1), to be
  replaced here by a connect-validated probe.
- **Segment tier** (`segmentizer/derive.py`): focus key already
  `(producer, output, app_id, workspace)` (SPEC-001 D8); closes on
  `compositor_disconnected`. `segmentizer/histogram.py::aggregate` still buckets
  `per_workspace_seconds` on **bare** `workspace` (R4 unmet — the one gap).

Niri is unreachable from the build jail; `$NIRI_SOCKET` lives on the host.

## 3. Forces & Constraints

- **Pure/imperative split** (project doctrine): native decode, projection
  transitions, and observation construction are pure and unit-testable without a
  live compositor; socket I/O, framing, reconnect live in the thin async shell.
- **Behaviour-preservation gate**: SL-002's suites must stay green unchanged; the
  Sway adapter, neutral core, and event schema are **not** touched (slice
  Non-Goal). Only `detect.py` (seam completion) and `histogram.py` (R4) change
  outside `compositor/niri/`.
- **No live compositor in-jail**: fixtures are the sole in-jail verification;
  fidelity to the real wire format is the central risk (SPEC-001 H1 flagged the
  rustdoc-vs-source hazard). Closed by a live golden capture (§9).
- **niri wire stability**: additive-only guarantee (fields/variants never renamed
  or removed) ⇒ adapters **ignore-and-continue** on unknown fields/variants, never
  crash. Pin niri-ipc `=26.4.0` (not semver-stable; SPEC-001 OQ-3).
- **Privacy** (`docs/privacy.md`): compositor metadata only — app_id/class, title,
  pid, workspace, output. No new capture surface.
- **One compositor at a time** (SPEC-001 H5): a single `raw/desktop-DAY.jsonl`
  never interleaves two producers; `producer` is constant intra-day.

## 4. Guiding Principles

- **Structural symmetry with Sway.** Both adapters are projection adapters behind
  the same contract (SPEC-001 D5). Reuse the module shape, don't reinvent it.
- **Neutrality is subtraction.** The projection accumulates native events; the
  session emits neutral *diffs* (SPEC-001 D10), never native events verbatim.
- **Purity first.** The accumulator is a total pure function; all impurity
  (socket, buffering, prior-state comparison) is confined to the thin session/
  protocol shell.
- **No false unification** (SPEC-001 D4). The shared model carries only
  WindowRef/DesktopState/DesktopObservation. No niri columns/named-workspace
  concepts leak up; no fabricated Sway concepts.

## 5. Proposed Design

### 5.1 System Model

```
compositor/niri/
  protocol.py    IMPURE — AF_UNIX/SOCK_STREAM to $NIRI_SOCKET; send "EventStream";
                 assert {"Ok":"Handled"} ack; yield one json.loads() per line.
                 (The sway/_i3ipc.py analogue. Deferred import — no niri dep on the
                 --help / arg-parse path.)
  projection.py  PURE — NiriProjection accumulator + to_state() transitive lookup.
                 Focus derives from the focused workspace's active_window_id, not
                 from WindowFocusChanged (DL-6, golden-capture-driven).
  session.py     NiriSession(CompositorSession) + NiriClient(CompositorClient):
                 burst-completion gate (D3a), diff emission (D10). Snapshot-first
                 observation stream.
```

Data flow:

```
$NIRI_SOCKET → protocol.frames() → NiriSession:
    accumulate burst via NiriProjection.apply(event)*
    once both WindowsChanged + WorkspacesChanged applied → yield
        DesktopObservation("snapshot", …)                         (DL-2)
    live deltas → apply → diff vs prior DesktopState → yield workspace_focus/
                  window_focus/window_title (neutral names, deriver contract)
    EOF → generator returns → run_watcher emits compositor_disconnected + backoff
```

`run_watcher` supplies the lifecycle events and the snapshot-first reconnect
pairing (SPEC-001 D3c) unchanged — SL-003 adds no lifecycle-event code.

### 5.2 Interfaces & Contracts

```python
# protocol.py (impure shell)
async def frames(sock_path: str, *, connect_timeout: float = 2.0) -> AsyncIterator[dict]:
    """Connect, send "EventStream", assert {"Ok":"Handled"}, yield json.loads/line.
    Raises on connect failure / bad ack → run_watcher turns it into a disconnect.
    The connect + ack read are bounded by connect_timeout so a wedged niri
    (socket accepts, handler hung) fails fast instead of stalling (F-5)."""

# projection.py (pure)
@dataclass(frozen=True, slots=True)
class NiriWindow:     # adapter-private; only the neutral subset is surfaced
    id: int; app_id: str | None; pid: int | None; title: str | None
@dataclass(frozen=True, slots=True)
class NiriWorkspace:
    id: int; name: str | None; idx: int; output: str | None
    active_window_id: int | None   # niri's per-workspace focus (WorkspaceActiveWindowChanged)
@dataclass(frozen=True, slots=True)
class NiriProjection:
    windows_by_id:      Mapping[int, NiriWindow]    = field(default_factory=dict)
    workspaces_by_id:   Mapping[int, NiriWorkspace] = field(default_factory=dict)
    focused_workspace_id: int | None = None    # the globally-focused workspace
    def apply(self, event: dict) -> "NiriProjection": ...   # total, ignore-unknown
    def to_state(self) -> DesktopState: ...

# session.py (impure glue)
class NiriSession:   # CompositorSession
    async def observations(self) -> AsyncIterator[DesktopObservation]: ...
class NiriClient:    # CompositorClient
    producer = "niri"
    def session(self) -> AbstractAsyncContextManager[NiriSession]: ...
```

**Event → mutation** (`apply`; unknown variants/fields ignored):

| niri event | mutation |
|---|---|
| `WindowsChanged {windows}` | full-state replace `windows_by_id` |
| `WorkspacesChanged {workspaces}` | full-state replace `workspaces_by_id`; set `focused_workspace_id` ← the `is_focused` workspace |
| `WindowOpenedOrChanged {window}` | upsert (novelty = id unseen; open ≡ mutate) |
| `WindowClosed {id}` | drop id from `windows_by_id` (before any reuse — D11) |
| `WorkspaceActivated {id, focused}` | if `focused`: `focused_workspace_id ← id` |
| `WorkspaceActiveWindowChanged {workspace_id, active_window_id}` | set that workspace's `active_window_id` |
| `WindowFocusChanged`, `WindowFocusTimestampChanged`, `OverviewOpenedOrClosed`, `KeyboardLayoutsChanged`, `ConfigLoaded`, `CastsChanged` | **ignored** — not focus signals in this model (DL-6) |

**`to_state()` — transitive lookup** (SPEC-001 D4; no `output` on Window). Focus
flows *workspace → active window*, never *window → workspace* (DL-6):

```
ws = workspaces_by_id.get(focused_workspace_id)
w  = windows_by_id.get(ws.active_window_id)  if ws and ws.active_window_id else None
→ DesktopState(
    window   = WindowRef(w.id, w.app_id, w.pid, w.title)  if w else None,
    workspace= ws.name if ws and ws.name else (str(ws.idx) if ws else None),
    output   = ws.output if ws else None)
```

Any missing link → that field is `None` (best-effort; matches `DesktopState`
optionality). **`workspace` = niri name when present, else the index as a string**
(DL-1); `output` is the load-bearing disambiguator (why D4 keeps it first-class).
An empty focused workspace (`active_window_id: None`, e.g. the "emacs" scratch
workspace in the golden capture) → `window = None` with `workspace`/`output`
retained: a real no-window dwell, correctly distinct from overview (DL-6).

### 5.3 Data, State & Ownership

- `NiriProjection` is **adapter-private** state, owned by the session, rebuilt from
  scratch on every (re)connect from the fresh initial burst — never carried across
  a disconnect (avoids stale-projection bugs).
- The neutral `DesktopState` is the only thing that crosses the adapter boundary.
  `NiriWindow`/`NiriWorkspace` never escape `compositor/niri/`.
- The store/schema are unchanged: Niri observations flow through the same
  `encode(obs, "niri")` → `raw/desktop-DAY.jsonl` + `current/desktop.json` path
  SL-002 built. `producer="niri"` is the only new value.

### 5.4 Lifecycle, Operations & Dynamics

- **Connect**: `frames()` opens the socket, handshakes, streams. `NiriClient.session()`
  is the async ctx-mgr `run_watcher` drives.
- **Initial burst → snapshot (D3a, DL-2).** The session runs a two-mode state
  machine. The golden capture (§9) settled the terminator: the burst carries **no
  reliable `WindowFocusChanged`** (capture 2's burst ends at `CastsChanged` with no
  focus event at all), and initial focus is carried by the `is_focused` /
  `active_window_id` flags *inside* the full-state events. So:
  - *Burst mode* (before the snapshot): buffer `apply()` calls. The snapshot is
    emitted **once both `WindowsChanged` and `WorkspacesChanged` have been applied**
    (DL-2) — those two full-state events are exactly the categories `to_state`
    needs; trailing burst noise (`KeyboardLayoutsChanged`, `OverviewOpenedOrClosed`,
    `ConfigLoaded`, `CastsChanged`) is processed in live mode and changes nothing.
  - **An empty/no-focus snapshot is valid** — a workspace with `active_window_id:
    None` yields `DesktopState()` with `window=None`; this is what makes INV-N2 hold
    on an idle desktop.
  - EOF during burst mode (only one full-state event seen) → generator returns
    having yielded nothing → partial burst discarded; `run_watcher` emits
    `compositor_disconnected` and backs off.
- **Live deltas → diff emission (D10)**: once the snapshot is emitted the session
  is in *live mode*; after each event compute `projection.to_state()` and emit the
  neutral event named by the highest-precedence changed field —
  `workspace_focus` on workspace/output change, else `window_focus` on focused-window
  change, else `window_title` on title change — carrying the full new state. (An
  empty-workspace switch changes both workspace and window in one event; one
  `workspace_focus` observation carrying `window=None` closes/opens the segment
  correctly, since the deriver rekeys from the observation's `DesktopState`.) A
  `WindowOpenedOrChanged` from resize/column-move (title unchanged) emits nothing.
- **Overview is inert by construction (DL-6).** Opening overview emits
  `WindowFocusChanged {id: None}` (then restores on close), but the model **ignores
  `WindowFocusChanged` entirely** — overview never touches `focused_workspace_id` or
  any workspace's `active_window_id`, so the projected state is unchanged and **no
  observation is emitted**. A brief overview gesture cannot flap the segment stream,
  with no lookahead, flag, or special-casing. When overview is used to *switch*
  workspaces (the user's sole use), the `WorkspaceActivated` that lands the switch
  drives the transition; the overview interval stays attributed to the source until
  it lands. **Residual (R5, much reduced):** `current/desktop.json` holds the
  last-focused window for the duration of the gesture only — intended (don't count
  overview as focus), and it updates the instant the switch lands.
- **Disconnect/reconnect (D3c)**: EOF/error → `run_watcher` emits
  `compositor_disconnected`, backs off, reconnects; the fresh session's snapshot-
  first stream gives the deriver a matching close/reopen. Handled by SL-002.
- **Detection (D7)** — `detect.py::select_client`:
  - `niri` / `sway` → that client unconditionally (explicit choice trusts the user).
  - `auto` → **connect-validated** probe (not env presence): for each set socket
    var, attempt `_probe` (connect, send `"EventStream"`, read ack, close) **under a
    bounded timeout (F-5)** so a wedged compositor whose socket still accepts fails
    the probe and falls through rather than hanging startup; use the one that
    connects; both connect → **NIRI wins** (stated, not list-order); none connect →
    raise, listing what was tried. Replaces the RV-001 F-1 `SWAYSOCK` stand-in and
    completes D7 for two adapters.
  - Because Niri is live and Sway dead, `--compositor auto` resolves to Niri on the
    host — live data switches on with no flag.
- **Histogram (R4)** — `histogram.py::aggregate`: `per_workspace_seconds` buckets
  on `(output, workspace)` rendered as a flat `"output/workspace"` string key
  (`"eDP-1/1"` ≠ `"DP-2/1"`); `per_app_seconds` and `per_hour_seconds` unchanged.
  SATAN-safe: `activity_read` forwards the histogram dict verbatim to the LLM and
  never keys into `per_workspace_seconds` in Elisp (verified against
  `satan-tools-activity.el`), so the key-shape change breaks no consumer code.

### 5.5 Invariants, Assumptions & Edge Cases

- **INV-N1** — `NiriProjection.apply` is total and pure: unknown event variant or
  unknown field → return an equal/updated projection, never raise (additive-only
  wire stability).
- **INV-N2** — the session's first yielded observation is always `snapshot` or
  nothing (never a delta first); guarantees the pull→push contract. The snapshot
  may carry an **empty `DesktopState()`** (no-focus startup) — empty is a valid
  snapshot, not a withheld one (§5.4, DL-2).
- **INV-N3** — neutral event **names** exactly match the deriver's contract
  (`snapshot`, `window_focus`, `window_title`, `workspace_focus`); a rename
  silently stops segments closing (SPEC-001 H4).
- **ASM-1 (CONFIRMED by golden capture — was the F-2 lock gate)** —
  `Workspace.output` is the DRM connector name (`"DP-3"` in the capture), the *same*
  space as Sway's `output` (SPEC-001 D4). The two host captures (§9) confirm every
  workspace carries an `output` connector-name string, closing Q1: `DesktopState.output`,
  the D4 cross-producer equivalence, and the DL-5 `"output/workspace"` histogram key
  all rest on verified ground. (Only one output, `DP-3`, was live, so two-output
  disambiguation is confirmed in principle — `output` is a per-workspace connector
  string — not directly exercised; PHASE-02's equivalence test covers the two-output
  shape with fixtures.)
- **Edge — burst-order independence**: `WindowsChanged`/`WorkspacesChanged` may
  arrive in either order (capture 2: workspaces first; capture 1: also workspaces
  first — H1-a); `to_state` tolerates a `focused_workspace_id` with no workspace
  yet, or an `active_window_id` with no window yet (→ `None`s). The snapshot waits
  for *both* full-state events (DL-2), so a live-mode diff never fires on a
  half-built projection.
- **Edge — id reuse**: window ids are opaque and reused across lifetimes;
  `WindowClosed` drops the id before any reuse, so novelty detection stays sound
  (SPEC-001 D11).
- **Edge — xwayland app_id**: Niri surfaces XWayland `app_id` via
  xwayland-satellite; strings may differ from Sway's `window_properties.class`.
  Inert here (histogram `per_app` keys on whatever the producer emits; one producer
  per era).

## 6. Open Questions & Unknowns

- **OQ-5 (SPEC-001) — fixture capture.** RESOLVED: **hybrid** — two live golden
  NDJSON captures from the host `$NIRI_SOCKET` (capture 1: burst + empty-workspace
  switch; capture 2: overview flap + in-overview workspace switching — together they
  prove wire format, close ASM-1/D4, and settle the terminator + DL-6 focus model),
  plus hand-authored edge-case fixtures (partial burst, reconnect, resize-no-title)
  the live captures cannot force on demand. Capture protocol in §9. Pinned to
  niri-ipc `=26.4.0`.
- **Q1 (CLOSED — golden capture, 2026-07-18)** — ASM-1: `Workspace.output` *is* the
  DRM connector name on live Niri (`"DP-3"`). Two host captures confirmed it; the
  design→plan gate is cleared. The same captures also disproved the original
  first-`WindowFocusChanged` terminator and drove the DL-6 focus model (see §10).
- **Q2 (deferred to SL-004)** — SATAN's semantic understanding of the new
  `"output/workspace"` histogram keys (docs, prompt). No code dependency; not
  gating.

## 7. Decisions, Rationale & Alternatives

- **DL-1 — unnamed workspace renders as its index string.** `workspace = name or
  str(idx)`. Non-null, human-legible, matches Sway's named-string shape;
  disambiguated across outputs by first-class `output` + D8's `(output, workspace)`
  key. *Alternatives:* `None` when unnamed (many null buckets, thinner signal);
  composite `"output:idx"` (re-Sway-shapes the model, double-counts output in D8).
- **DL-2 — burst terminator = both `WindowsChanged` + `WorkspacesChanged` applied.**
  *Revised from "first `WindowFocusChanged`" by the golden capture:* capture 2's
  initial burst carries no `WindowFocusChanged` at all (it ends at `CastsChanged`),
  disproving the original terminator. The two full-state events are the categories
  `to_state` needs; both-seen is deterministic and testable. *Alternatives:* first
  `WindowFocusChanged` (disproven); a timeout (non-deterministic, rejected).
- **DL-3 — initial focus derives from the snapshot flags, not a focus event.**
  Follows from DL-2/DL-6: the burst carries focus via `WorkspacesChanged.is_focused`
  (→ `focused_workspace_id`) and each workspace's `active_window_id`, so no
  `WindowFocusChanged` is required to build the first snapshot. *(Supersedes the
  earlier "`focus:None` emits nothing" formulation — obsolete under DL-6, where
  `WindowFocusChanged` is ignored outright.)*
- **DL-4 — `auto` prefers Niri on a both-connect tie.** SPEC-001 D7. Matches the
  live reality; explicit, not list-order.
- **DL-5 — histogram `per_workspace` keyed `"output/workspace"`, `per_app`
  unchanged.** Minimal correct de-conflation given one producer/day (H5).
  *Alternative:* nested `{output: {ws: s}}` — rejected (changes value type for no
  gain; flat string is self-describing and JSON-flat for the LLM consumer).
- **DL-6 — focus derives from the focused workspace's `active_window_id`;
  `WindowFocusChanged`/`OverviewOpenedOrClosed` are ignored.** *Golden-capture-driven.*
  niri maintains a per-workspace active window (`WorkspaceActiveWindowChanged`,
  seeded in the snapshot) that overview never perturbs, and the user's invariant —
  a window is only ever focused on the active workspace — makes
  `focused_workspace.active_window_id` identical to the truly-focused window. So the
  projection tracks `focused_workspace_id` (from `WorkspaceActivated`/`is_focused`)
  and reads the window transitively, ignoring the raw `WindowFocusChanged` stream.
  This makes overview flapping impossible *by construction* (no lookahead, no flag)
  and keeps the empty-workspace dwell distinct (`active_window_id: None` → real
  no-window state) — the two `focus:None` causes the capture revealed. *Alternatives:*
  (a) `WindowFocusChanged` primary + suppress `id:None` while an overview flag is set
  — rejected: the capture proves the focus event *precedes* `OverviewOpenedOrClosed`,
  so the flag isn't set yet when the null lands; (b) `WindowFocusChanged` primary +
  occupancy-test on `id:None` — rejected as strictly more code than (DL-6) for the
  same behaviour, given the active-workspace invariant. Floating-window focus on a
  non-active workspace is judged impossible (user-confirmed); a PHASE-01 capture
  spot-checks it, with (b) as the documented fallback if it ever holds.
- **Inherited (SPEC-001):** D3 (direct JSON socket, no Rust sidecar), D4 (output
  first-class), D9 (emit-time timestamps, ignore niri `Timestamp`), D10 (diff
  emission), D11 (scoped id uniqueness). Not re-litigated here.

## 8. Risks & Mitigations

- **R1 — fixture fiction (rustdoc vs live wire).** *Mitigation:* the golden capture
  is a real host session; hand-authored fixtures are cross-checked against it for
  shape (field names, variant tags). ASM-1 falls out of the same capture.
- **R2 — burst-completion (resolved by DL-2).** The terminator is now "both
  `WindowsChanged` + `WorkspacesChanged` applied" — the two full-state categories
  `to_state` reads. Trailing burst events (`OverviewOpenedOrClosed`, `CastsChanged`,
  …) are ignored or inert in live mode, so the snapshot cannot be partial for a
  reason that matters. `to_state` remains order-tolerant as defence in depth.
- **R3 — `output` absent on some workspaces** (e.g. a disabled monitor). *Mitigation:*
  `to_state` yields `output=None`; histogram key `"None/1"` is ugly but correct and
  rare; not gating.
- **R4 — Sway/Niri histogram key mixing across the migration day.** *Mitigation:*
  Sway data is dead (memory); no live Sway stream collides. Documented in notes.
- **R5 — `current/desktop.json` staleness during overview (much reduced under
  DL-6).** Overview no longer produces any observation, so `current` holds the
  last-focused window only for the *duration of the overview gesture* — intended
  (overview is not focus) and bounded to the gesture; it updates the instant a
  `WorkspaceActivated` lands the switch. Empty-workspace dwell now updates `current`
  correctly (window→None), where the old DL-3 suppression left it stale. No open
  tradeoff remains.

## 9. Quality Engineering & Validation

- **Golden captures (host, outside jail — DONE at the design→plan boundary,
  2026-07-18).** Three real sessions were recorded from the host `$NIRI_SOCKET`
  (python snippet: connect, send `"EventStream"`, drain the ack, `tee`):
  - **capture 0** (`niri-golden.ndjson`, saved to repo root) — startup burst +
    within-workspace focus cycling (`WorkspaceActiveWindowChanged`→
    `WindowFocusChanged`) + a `WindowOpenedOrChanged` title mutate. The clean
    baseline; confirms the DL-6 coupling.
  - **capture 1** — startup burst + switches to empty ("emacs") and populated
    workspaces (the empty-workspace `focus:None` case).
  - **capture 2** — startup burst (no `WindowFocusChanged`) + repeated overview
    toggles and in-overview workspace switching (the overview `focus:None` case).

  They closed the gates: (a) **ASM-1** — every workspace carries `output: "DP-3"`, a
  DRM connector name ✓; (b) **terminator** — capture 2's burst has no
  `WindowFocusChanged`, so the terminator is both full-state events (DL-2) ✓; (c)
  the `focus:None` split (overview vs empty-workspace) + the
  `WorkspaceActiveWindowChanged`→`WindowFocusChanged` coupling drove DL-6 ✓.
  **PHASE-01 commits the raw captures verbatim under `tests/fixtures/niri/`**
  (capture 0 is already in the repo root; re-capture 1/2 per the snippet if lost),
  version-stamped `niri --version` in the fixture header (pin `=26.4.0`). See §10
  for the full capture findings.
- **Pure projection tests** (`test_compositor_niri_projection.py`): burst-order
  permutations, novelty/upsert, `WindowClosed` id-drop, transitive-miss `None`s,
  unknown-variant ignore, **focus via `active_window_id`** (`WorkspaceActivated` +
  `WorkspaceActiveWindowChanged` move focus; `WindowFocusChanged` is a no-op),
  empty-workspace → `window=None`.
- **Session tests** (`test_compositor_niri_session.py`): snapshot-first, partial-
  burst discard (DL-2), **overview inert** (an `OverviewOpenedOrClosed` +
  `WindowFocusChanged{id:None}` pair emits nothing — driven from capture 2),
  **empty-workspace switch** emits `workspace_focus` with `window=None` (capture 1),
  title-diff suppression (D10), resize-no-emit.
- **Detection tests** (`test_compositor_detect.py`, extended): `niri` explicit,
  `auto` both-connect→niri, auto one-connect, auto none→raises; probe uses a fake
  socket, no live compositor.
- **Histogram tests** (`test_segmentizer_histogram.py`, extended): two workspaces
  same idx different output do **not** conflate; `per_app` unchanged.
- **Cross-compositor equivalence** (`test_compositor_equivalence.py`): the same
  logical scenario (focus A→B across two workspaces on two outputs) driven through
  both the Sway and Niri sessions. **"Comparable" is pinned (F-6)** — the assertion
  is: (a) the **event-name sequence is equal** (`snapshot`, `window_focus`,
  `workspace_focus`, …); (b) the **`output` field matches** (both DRM connector
  names — the D4 claim); (c) the **workspace-transition *shape* matches** (same
  count/order of distinct workspace values), while the workspace *value* and
  `app_id` *string* are permitted to diverge (DL-1 idx-string vs Sway name; XWayland
  `class` vs xwayland-satellite — §5.5). Fixtures are hand-built to be structurally
  aligned so this is a falsifiable equality, not a judgement call.
- **Gate**: full suite green + ruff clean (run direct in-jail; `just` unavailable).
  SL-002 suites stay green unchanged (behaviour-preservation).
- **VH (host, non-gating)**: `panopticon-desktop --compositor auto` on the live
  Niri host writes `current/desktop.json` with a real focused window.

## 10. Review Notes

RV-002 (six findings, all disposed) is the adversarial-review ledger for this
design; its fixes are integrated above.

### Golden-capture findings (2026-07-18) — the design→plan gate

Two live host captures (§9) closed Q1/ASM-1 and materially revised the focus
model. What they proved:

- **ASM-1 confirmed** — every workspace carries `output: "DP-3"` (DRM connector
  name). D4 / DL-5 rest on verified ground. (Single output live; two-output shape
  deferred to fixtures.)
- **Terminator disproved → DL-2 revised.** Capture 2's initial burst is
  `WorkspacesChanged, WindowsChanged, KeyboardLayoutsChanged,
  OverviewOpenedOrClosed, ConfigLoaded, CastsChanged` — **no `WindowFocusChanged`**.
  The first-focus-event terminator was wrong; the terminator is now both full-state
  events (DL-2), and initial focus comes from the snapshot flags (DL-3).
- **Two causes of `focus:None`, discriminated → DL-6.** Overview open emits
  `WindowFocusChanged{id:None}` **before** `OverviewOpenedOrClosed{is_open:true}`
  (killing any overview-flag gate); an empty-workspace switch emits
  `WorkspaceActivated` **then** `WindowFocusChanged{id:None}`. Deriving focus from
  the focused workspace's `active_window_id` (which overview never touches) makes
  overview inert by construction and keeps empty-workspace dwell as a real
  `window=None` state — no lookahead, no flag.
- **DL-6 coupling confirmed** — capture 0 (`niri-golden.ndjson`) shows
  `WorkspaceActiveWindowChanged{4,N}` **immediately precedes** every
  `WindowFocusChanged{N}` for within-workspace focus moves (106→104→106). niri's
  per-workspace `active_window_id` faithfully tracks focus, so reading it (and
  ignoring `WindowFocusChanged`) is lossless — the empirical backbone of DL-6.
- **Ignore-set widened.** The stream carries `KeyboardLayoutsChanged`,
  `OverviewOpenedOrClosed`, `ConfigLoaded`, `CastsChanged`,
  `WorkspaceActiveWindowChanged` (now *used*, not ignored), and
  `WindowFocusTimestampChanged` — all handled by ignore-and-continue except the two
  the model consumes. Vindicates INV-N1.
- **Shapes validated** — `app_id` plain strings (incl. xwayland-satellite
  `com-fastmail-fastmail`), `title`/`pid` present, window `workspace_id` can be
  `null` (floating Signal mid-move), unnamed workspaces (`name:null, idx:9/10/11`)
  confirm DL-1.

### Phase shape (provisional — finalised at /plan)

1. **PHASE-01 — Protocol + pure projection.** `niri/protocol.py` (framing + ack)
   and `niri/projection.py` (accumulator + `to_state`). Commit both golden captures
   under `tests/fixtures/niri/`; green against them + hand-authored edges. ASM-1
   already closed (design gate) — PHASE-01 spot-checks the floating-focus edge (DL-6).
2. **PHASE-02 — Session + normalization + equivalence.** `niri/session.py`
   (burst-completion gate, diff emission, overview-inert), snapshot-first stream,
   cross-compositor equivalence tests.
3. **PHASE-03 — Live wire-up.** `detect.py` D7 completion (connect-validated probe,
   both-set resolution, retire the SWAYSOCK stand-in) + `histogram.py` R4
   de-conflation. `--compositor auto` runs Niri live end-to-end.
