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
  session.py     NiriSession(CompositorSession) + NiriClient(CompositorClient):
                 burst-buffer gate (D3a), diff emission (D10), focus:None
                 continuation (D3b). Snapshot-first observation stream.
```

Data flow:

```
$NIRI_SOCKET → protocol.frames() → NiriSession:
    accumulate burst via NiriProjection.apply(event)*
    on first WindowFocusChanged → yield DesktopObservation("snapshot", …)
    live deltas → apply → diff vs prior DesktopState → yield window_focus/
                  window_title/workspace_focus (neutral names, deriver contract)
    EOF → generator returns → run_watcher emits compositor_disconnected + backoff
```

`run_watcher` supplies the lifecycle events and the snapshot-first reconnect
pairing (SPEC-001 D3c) unchanged — SL-003 adds no lifecycle-event code.

### 5.2 Interfaces & Contracts

```python
# protocol.py (impure shell)
async def frames(sock_path: str) -> AsyncIterator[dict]:
    """Connect, send "EventStream", assert {"Ok":"Handled"}, yield json.loads/line.
    Raises on connect failure / bad ack → run_watcher turns it into a disconnect."""

# projection.py (pure)
@dataclass(frozen=True, slots=True)
class NiriWindow:     # adapter-private; only the neutral subset is surfaced
    id: int; app_id: str | None; pid: int | None; title: str | None
    workspace_id: int | None
@dataclass(frozen=True, slots=True)
class NiriWorkspace:
    id: int; name: str | None; idx: int; output: str | None; is_active: bool
@dataclass(frozen=True, slots=True)
class NiriProjection:
    windows_by_id:    Mapping[int, NiriWindow]    = field(default_factory=dict)
    workspaces_by_id: Mapping[int, NiriWorkspace] = field(default_factory=dict)
    focused_window_id: int | None = None
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
| `WorkspacesChanged {workspaces}` | full-state replace `workspaces_by_id` |
| `WindowOpenedOrChanged {window}` | upsert (novelty = id unseen; open ≡ mutate) |
| `WindowClosed {id}` | drop id from `windows_by_id` (before any reuse — D11) |
| `WindowFocusChanged {id}` | set `focused_window_id` (may be `None`) |
| `WorkspaceActivated {id, focused}` | flip `is_active` for that workspace's output |

**`to_state()` — transitive lookup** (SPEC-001 D4; no `output` on Window):

```
w  = windows_by_id.get(focused_window_id)
ws = workspaces_by_id.get(w.workspace_id)          if w else None
→ DesktopState(
    window   = WindowRef(w.id, w.app_id, w.pid, w.title)  if w else None,
    workspace= ws.name if ws and ws.name else (str(ws.idx) if ws else None),
    output   = ws.output if ws else None)
```

Any missing link → that field is `None` (best-effort; matches `DesktopState`
optionality). **`workspace` = niri name when present, else the index as a string**
(DL-1); `output` is the load-bearing disambiguator (why D4 keeps it first-class).

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
- **Initial burst → snapshot (D3a)**: buffer `apply()` calls; emit the first
  `snapshot` observation **only on the first `WindowFocusChanged`** (the burst
  terminator). EOF before it → generator returns with nothing yielded → partial
  burst discarded, no half-built snapshot.
- **Live deltas → diff emission (D10)**: after each event compute
  `projection.to_state()`; emit only the neutral event whose projected value
  changed — `window_focus` on focused-id change, `window_title` on title change,
  `workspace_focus` on workspace/output change. A `WindowOpenedOrChanged` from
  resize/column-move (title unchanged) emits nothing.
- **`WindowFocusChanged {id: None}` (D3b)**: apply to projection but **emit no
  observation** → no segment boundary, current-state untouched → deriver sees
  continuation, not focus-loss. Overview toggling cannot flap the segment stream.
- **Disconnect/reconnect (D3c)**: EOF/error → `run_watcher` emits
  `compositor_disconnected`, backs off, reconnects; the fresh session's snapshot-
  first stream gives the deriver a matching close/reopen. Handled by SL-002.
- **Detection (D7)** — `detect.py::select_client`:
  - `niri` / `sway` → that client unconditionally (explicit choice trusts the user).
  - `auto` → **connect-validated** probe (not env presence): for each set socket
    var, attempt `_probe` (connect, send `"EventStream"`, read ack, close); use the
    one that connects; both connect → **NIRI wins** (stated, not list-order);
    none connect → raise, listing what was tried. Replaces the F-1 `SWAYSOCK`
    stand-in and completes D7 for two adapters.
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
  nothing (never a delta first); guarantees the pull→push contract.
- **INV-N3** — neutral event **names** exactly match the deriver's contract
  (`snapshot`, `window_focus`, `window_title`, `workspace_focus`); a rename
  silently stops segments closing (SPEC-001 H4).
- **ASM-1 (lock-gate)** — `Workspace.output` is the DRM connector name (e.g.
  `"eDP-1"`), the *same* space as Sway's `output` (SPEC-001 D4). Confirmed by the
  golden capture (§9) before the slice locks.
- **Edge — burst-order independence**: `WindowsChanged`/`WorkspacesChanged`/
  `WindowFocusChanged` may arrive in any order (H1-a); `to_state` tolerates a
  focused-id with no window yet, or a window with no workspace yet (→ `None`s).
- **Edge — id reuse**: window ids are opaque and reused across lifetimes;
  `WindowClosed` drops the id before any reuse, so novelty detection stays sound
  (SPEC-001 D11).
- **Edge — xwayland app_id**: Niri surfaces XWayland `app_id` via
  xwayland-satellite; strings may differ from Sway's `window_properties.class`.
  Inert here (histogram `per_app` keys on whatever the producer emits; one producer
  per era).

## 6. Open Questions & Unknowns

- **OQ-5 (SPEC-001) — fixture capture.** RESOLVED (this design): **hybrid** — one
  live golden NDJSON capture from the host `$NIRI_SOCKET` (proves wire format,
  closes ASM-1/D4), plus hand-authored edge-case fixtures (partial burst,
  focus:None, reconnect, resize-no-title) the live capture cannot force on demand.
  Capture protocol in §9. Pinned to niri-ipc `=26.4.0`.
- **Q1 (lock-gate)** — ASM-1: is `Workspace.output` literally the DRM connector
  name on live Niri? Confirmed by the golden capture before design locks.
- **Q2 (deferred to SL-004)** — SATAN's semantic understanding of the new
  `"output/workspace"` histogram keys (docs, prompt). No code dependency; not
  gating.

## 7. Decisions, Rationale & Alternatives

- **DL-1 — unnamed workspace renders as its index string.** `workspace = name or
  str(idx)`. Non-null, human-legible, matches Sway's named-string shape;
  disambiguated across outputs by first-class `output` + D8's `(output, workspace)`
  key. *Alternatives:* `None` when unnamed (many null buckets, thinner signal);
  composite `"output:idx"` (re-Sway-shapes the model, double-counts output in D8).
- **DL-2 — burst terminator = first `WindowFocusChanged`.** SPEC-001 D3a; the
  focus event reliably follows the full-state bursts. *Alternative:* a timeout —
  rejected (non-deterministic, untestable).
- **DL-3 — `focus:None` emits nothing.** Simplest realization of D3b continuation;
  no new neutral event, no deriver change. *Alternative:* a dedicated
  `focus_cleared` event — rejected (would need deriver logic to *not* close on it,
  more surface for the same result).
- **DL-4 — `auto` prefers Niri on a both-connect tie.** SPEC-001 D7. Matches the
  live reality; explicit, not list-order.
- **DL-5 — histogram `per_workspace` keyed `"output/workspace"`, `per_app`
  unchanged.** Minimal correct de-conflation given one producer/day (H5).
  *Alternative:* nested `{output: {ws: s}}` — rejected (changes value type for no
  gain; flat string is self-describing and JSON-flat for the LLM consumer).
- **Inherited (SPEC-001):** D3 (direct JSON socket, no Rust sidecar), D4 (output
  first-class), D9 (emit-time timestamps, ignore niri `Timestamp`), D10 (diff
  emission), D11 (scoped id uniqueness). Not re-litigated here.

## 8. Risks & Mitigations

- **R1 — fixture fiction (rustdoc vs live wire).** *Mitigation:* the golden capture
  is a real host session; hand-authored fixtures are cross-checked against it for
  shape (field names, variant tags). ASM-1 falls out of the same capture.
- **R2 — burst-completion false terminator.** If a real session emits a
  `WindowFocusChanged` mid-burst before all `WindowsChanged` arrive, the snapshot
  could be partial. *Mitigation:* `to_state` is order-tolerant; the golden capture
  is inspected for burst ordering; if disproven, fall back to first-live-delta as
  terminator (recorded, not built).
- **R3 — `output` absent on some workspaces** (e.g. a disabled monitor). *Mitigation:*
  `to_state` yields `output=None`; histogram key `"None/1"` is ugly but correct and
  rare; not gating.
- **R4 — Sway/Niri histogram key mixing across the migration day.** *Mitigation:*
  Sway data is dead (memory); no live Sway stream collides. Documented in notes.

## 9. Quality Engineering & Validation

- **Golden capture protocol (host, outside jail).** Connect and record a real
  session to a committed NDJSON fixture:
  ```
  socat -u UNIX-CONNECT:$NIRI_SOCKET - <<<'"EventStream"' | tee niri-golden.ndjson
  # or a 20-line python asyncio snippet; capture: startup burst, focus A→B across
  # two outputs, a title change, a workspace switch, an overview toggle (focus:None).
  ```
  Inspect it to (a) confirm ASM-1 (`output` = connector name), (b) confirm burst
  order + terminator (DL-2/R2), (c) seed `tests/fixtures/niri/`. Version-stamp with
  `niri --version` in the fixture header.
- **Pure projection tests** (`test_compositor_niri_projection.py`): burst-order
  permutations, novelty/upsert, `WindowClosed` id-drop, transitive-miss `None`s,
  unknown-variant ignore.
- **Session tests** (`test_compositor_niri_session.py`): snapshot-first, partial-
  burst discard (D3a), focus:None continuation (D3b), title-diff suppression
  (D10), resize-no-emit.
- **Detection tests** (`test_compositor_detect.py`, extended): `niri` explicit,
  `auto` both-connect→niri, auto one-connect, auto none→raises; probe uses a fake
  socket, no live compositor.
- **Histogram tests** (`test_segmentizer_histogram.py`, extended): two workspaces
  same idx different output do **not** conflate; `per_app` unchanged.
- **Cross-compositor equivalence** (`test_compositor_equivalence.py`): the same
  logical scenario (focus A→B across workspaces) driven through both the Sway and
  Niri sessions yields comparable `DesktopObservation` streams (event names +
  neutral state), proving the contract is genuinely neutral.
- **Gate**: full suite green + ruff clean (run direct in-jail; `just` unavailable).
  SL-002 suites stay green unchanged (behaviour-preservation).
- **VH (host, non-gating)**: `panopticon-desktop --compositor auto` on the live
  Niri host writes `current/desktop.json` with a real focused window.

## 10. Review Notes

<!-- Adversarial pass findings land here (or on an RV ledger). -->

### Phase shape (provisional — finalised at /plan)

1. **PHASE-01 — Protocol + pure projection.** `niri/protocol.py` (framing + ack)
   and `niri/projection.py` (accumulator + `to_state`). Green against hand-authored
   + golden fixtures. Closes ASM-1 via the capture.
2. **PHASE-02 — Session + normalization + equivalence.** `niri/session.py`
   (burst-gate, diff emission, focus:None), snapshot-first stream, cross-compositor
   equivalence tests.
3. **PHASE-03 — Live wire-up.** `detect.py` D7 completion (connect-validated probe,
   both-set resolution, retire the SWAYSOCK stand-in) + `histogram.py` R4
   de-conflation. `--compositor auto` runs Niri live end-to-end.
