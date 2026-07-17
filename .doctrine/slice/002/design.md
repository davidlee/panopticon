# Design SL-002: Compositor-neutral core and Sway migration

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SPEC-001, SL-003); doc-local refs bare — spec decisions D1..D11, spec open
     questions OQ-1..OQ-5, this design's decisions DD1..DD11, questions SQ1..SQ4,
     risks R1..R5. Adversarial review 2026-07-17: findings F1..F9 (design),
     V1..V8 (code-surface) folded — see §10. -->

Descends from SPEC-001 (`references --role implements`). SPEC-001 locks the
container-level decisions (D1–D11) and closed OQ-1/OQ-3; this design descends them
to the module/function level: **stand up the neutral core and move Sway behind it,
emitting the migrated `source:"desktop"` schema, behaviour-preserving bar the D5
focus fix.** Niri is SL-003; docs + unit cosmetics are SL-004.

**Operating reality (2026-07-17, owner):** the user runs **Niri**; the deployed
Sway watcher is **dormant** and desktop-attention data is **dead** right now
([[mem.fact.panopticon.niri-live-sway-dead]]). This reframes the slice: SL-002 is a
refactor of a *non-running* producer, so "behaviour preservation" protects the
**fixtures and the reference implementation**, not a live data stream — and there is
**no live-stream cutover** (see the F5 resolution in §7/DD11). Live data resumes at
**SL-003**, when Niri support lands. SL-002 is necessary scaffolding that, on its
own, produces nothing observable on this host.

## 1. Design Problem

`panopticon.sway_watcher` is Sway-shaped end to end: the runner pulls one atomic
`get_tree()` snapshot, the encoder hardcodes `make_event("sway", …)`, and the
segmentizer keys and closes on Sway-specific values. A second compositor (Niri,
SL-003) cannot ride this. This slice extracts a compositor-neutral core — model,
runner, event encoder, adapter contract, entrypoint/detection — and re-expresses
Sway as the first adapter behind it, **without regressing the existing Sway
fixtures** except the one deliberate D5 fix, and **emitting the final migrated
schema from the start** (SPEC-001 review correction 1) so SL-003 adds a `producer`
value, not a schema reshape.

The load-bearing risk is the neutral contract shape. Get it wrong and SL-003/SL-004
inherit a Sway-shaped core. The single most important call is the **pull→push
inversion** (D5/H2): the contract must let each adapter yield its *own* initial
snapshot, so `process_session` never calls `get_tree` and Niri's terminator-less
burst fits the same seam as Sway's atomic pull.

## 2. Current State

Verified against the tree (2026-07-17; reviewer B confirmed anchors accurate).
Files this slice restructures:

- `sway_watcher/runner.py` — `process_session` (`:55-83`) pulls `get_tree()`
  (`:68`), derives `focus_state_from_tree` (`:69`), emits `snapshot` (`:72`), writes
  `current/sway.json` (`:73`), then streams `transform`ed events (`:74-81`).
  `run_watcher` (`:86-121`) owns reconnect/backoff and emits the synthetic
  `sway_reconnected` (`:109`) / `sway_disconnected` (`:119`) events. `AsyncSession`
  (`:40-45`) is the leak: `events()` **and** `get_tree()`. Note: today's threaded-in
  `state` is discarded immediately (`:68-69` overwrites it) and the returned state
  is fed into a call that discards it (`:112`) — both are already vestigial (F3).
- `sway_watcher/events.py` — pure `transform` (`:33-43`); eight `make_event("sway",
  …)` call sites (`:84,110,136,173,186,194,199,203`); per-event field sets differ —
  `window_focus` carries id/app_id/pid/title/workspace/output, `workspace_focus`
  carries `old_workspace`/workspace/output (`:166-172`), `window_title` carries
  `old_title`/title (`:100-108`); the D5 bug at `_on_window_focus` (`:76-83`) copying
  `workspace`/`output` from prior state.
- `sway_watcher/state.py` — `FocusState` (`:19-38`, carries `con_id`),
  `app_id_from_container` (`:41-51`), `find_focused` (`:54-66`),
  `ancestor_name_of_type` (`:69-78`), `focus_state_from_tree` (`:81-98`) — the pure
  tree projection that derives workspace/output **correctly** via ancestry.
- `sway_watcher/ipc.py` — `Backoff` (`:60-88`, LIVE) + `IpcEvent` (`:37-42`, LIVE,
  imported by **both** `runner.py:34` **and** `_i3ipc.py:19`) alongside the DEAD
  `stream()`/`Ipc{Disconnected,Reconnected}`/`StreamMessage` (`:45-57,94-138`) — the
  D6 duplication. No production importer of the dead four (reviewer B, grep-confirmed).
- `sway_watcher/_i3ipc.py` — the only `i3ipc` importer; queue-bridge session that
  constructs `IpcEvent` in its handler (`:71`).
- `sway_watcher/__main__.py` — `panopticon-sway`; `--source` default `"sway"`
  (`:33-37`); `RawStore(args.source, …)` (`:61`).
- `store.py` — `RawStore` already source-parameterized: `raw/{source}-{day}.jsonl`
  (`:41`), `current/{source}.json` (`:45`, exactly one file per source), atomic
  `write_current` (`:56-67`).
- `schema.py` — `Event{v,ts,source,event,fields}`; `from_dict` validates *shape*
  only, no `source`/`event` value checks (`:56-69`); `make_event(source, event, …)`.
  `window_id` is an established field name (`browser.py:46/115/146` reads it).
- `segmentizer/__main__.py` — `_SOURCES` (`:36-39`); per-source loop (`:59-78`);
  `derive` called **without** a `source` arg (`:72`) → falls to its `"sway"`
  default; `seg_path` overwrites per `(seg_prefix, day)` via `os.replace` (`:73-76`).
- `segmentizer/derive.py` — `derive_segments(source="sway", …)` (`:32-37`); focus key
  `(app_id, workspace)` (`:69-74`); segment body stamps `source` (`:106`); closes on
  literal `"sway_disconnected"` (`:82`).
- `segmentizer/histogram.py` — `aggregate` buckets `per_app_seconds` on `f["app_id"]`
  and `per_workspace_seconds` on `f["workspace"]` **alone** (`:54-57`) — it does not
  read `producer`/`output` (reviewer B; the D8 segment-key change does *not*
  auto-ripple here — see F4).
- `segmentizer/retention.py` — `_SEGMENT_PREFIX_FOR_RAW` (`:26-29`);
  `_source_from_raw_name` already generic (`:93-98`); optimistic-fallback reap
  (`:101-108`) — the OQ-4 hazard site (reduced by the dormant-Sway reality, §7/DD11).

Out-of-repo readers of `current/sway.json` (SPEC-001 D2/OQ-1, read-only, **not**
edited here): four verbatim-passthrough sites in SATAN + the sleipnir doctor.

## 3. Forces & Constraints

- **Behaviour preservation (gate).** Existing Sway suites are the proof. They move
  with their modules; assertions change **only** where a deliberate rename
  (`con_id`→`window_id`, `sway_*`→`compositor_*`) or the new contract shape requires
  it — enumerated in §9, never silent. With Sway dormant this protects the reference
  implementation and regression fixtures, not a live stream.
- **Purity split.** Native decode, tree projection, observation construction, and
  event encoding stay pure/unit-testable. `get_tree`, sockets, reconnect, backoff,
  disk live in the async shell (the adapter session + runner).
- **Schema-once (review correction 1).** Emit `source:"desktop"` + `producer` +
  `window_id` from the first phase, so SL-003 adds a producer value, not a reshape.
- **Compat surface is exactly one file** (D2): `current/sway.json` side-write. No
  other back-compat carried; `con_id` dropped as a field *name*, not dual-emitted.
- **Encoder ↔ deriver lockstep (F6).** The segment deriver keys on literal event
  names (H4). During the retention window, historical `raw/sway-*.jsonl` still carry
  the old `sway_disconnected` name, so the deriver must close on **both**
  `sway_disconnected` and `compositor_disconnected` — the rename and this
  dual-trigger land in the same slice.
- **Single-adapter honesty.** Niri is out of scope; the detection/CLI *structure*
  must admit a second adapter (SL-003) without SL-002 pretending Niri exists — a
  `niri` branch that raises, not a stub that lies.

## 4. Guiding Principles

- Ride the existing seams (no parallel implementation): `focus_state_from_tree`,
  `RawStore`, `Backoff`, `transform`'s pure-mapping shape all survive — relocated and
  renamed, not rewritten.
- One place per concern: `producer`/`source` injection lives **only** in the neutral
  encoder; adapters stay producer-agnostic and emit neutral observations.
- The runner learns *nothing* new about compositors — it loses knowledge (`get_tree`
  goes away). Neutrality is subtraction, not addition.
- Make the D5 fix legible: isolate it behind its own before/after test so the
  "fixtures stay green" gate stays meaningful through a large mechanical move.

## 5. Proposed Design

### 5.1 System Model

New package `panopticon/compositor/` + entrypoint package
`panopticon/desktop_watcher/`:

```
compositor/
  model.py     WindowRef · DesktopState · DesktopObservation
               CompositorSession · CompositorClient (protocols)
  runner.py    run_watcher + process_session (neutral; NO get_tree); Backoff (moved)
  events.py    encode(observation, producer) -> schema.Event {source:"desktop", …}
  detect.py    select_client(compositor) -> (CompositorClient, producer)   [D7, SL-002 subset]
  sway/
    project.py   tree-walk helpers (from state.py) re-typed to build DesktopState;
                 IpcEvent (relocated from ipc.py — V1)
    session.py   CompositorSession over i3ipc: live projection + D5 fix + neutral obs
    _i3ipc.py    i3ipc CompositorClient (moved; import of IpcEvent repointed)
desktop_watcher/
  __main__.py  panopticon-desktop --compositor auto|sway ; wires client→runner→store
```

`sway_watcher/` collapses to a thin `panopticon-sway` compatibility wrapper (DD10).
`FocusState` is **subsumed** by `DesktopState`/`WindowRef` (DD3/V6) — not retained
alongside — so there is one focus model, not two.

### 5.2 Interfaces & Contracts

**The inversion (DD2).** The session yields normalized observations; its *first*
observation is always the snapshot. The runner no longer knows how state is acquired.

```python
class CompositorSession(Protocol):
    def observations(self) -> AsyncIterator[DesktopObservation]: ...

class CompositorClient(Protocol):
    producer: str                                   # "sway" | "niri"
    def session(self) -> AbstractAsyncContextManager[CompositorSession]: ...
```

```python
async def process_session(session, store, producer) -> None:   # no return (F3)
    async for obs in session.observations():        # first obs is the snapshot
        ev = encode(obs, producer)                  # source:"desktop", producer, window_id
        store.write(ev)
        store.write_current(obs.state.to_dict())    # current/desktop.json (+ sway.json compat)
```

`run_watcher` keeps the reconnect/backoff loop and remains the emitter of the
lifecycle events — now neutral: `compositor_reconnected` on a non-first connect,
`compositor_disconnected` on drop, both via `encode`. The fresh session supplies the
post-reconnect snapshot (D3(c)). The state threading and EOF-return that today's
runner carries are dropped as vestigial (F3, §2).

### 5.3 Data, State & Ownership

- **WindowRef** — `{window_id, app_id, pid, title}` (all optional). `window_id` is
  the renamed `con_id` (DD5); scoped-unique per D11.
- **DesktopState** — `{window: WindowRef | None, workspace, output}`. `to_dict()`
  **flattens** to `{window_id, app_id, pid, title, workspace, output}` — the exact
  key set today's `FocusState.to_dict` writes, `con_id`→`window_id`. This is the
  `current/desktop.json` (and compat `current/sway.json`) payload.
- **DesktopObservation** — `{event: str, fields: dict, state: DesktopState}`. `fields`
  is the **per-event** payload preserved verbatim (F8) — `old_workspace`/`old_title`
  and the distinct field sets survive; only `state` is re-derived by the projection.
  `encode` adds `source` + `producer`. Snapshot is `event="snapshot"`; no separate type.
- Ownership: the adapter owns native projection + observation construction; the
  neutral encoder owns schema shape; the store owns files; the runner owns the
  connect/reconnect lifecycle and the two lifecycle events.

### 5.4 Lifecycle, Operations & Dynamics

**Sway adapter session (DD6, the D5 fix — a live projection per D5).** The adapter
holds a projection: a `container_id → (workspace, output)` location index plus the
currently-focused container. On connect: `get_tree()` seeds the index and yields the
`snapshot` observation. Then per i3ipc event:

- `window::focus` — window **identity** (`window_id`/app_id/pid/title) comes from the
  event payload (deterministic, no round-trip, no race); **workspace/output** come
  from the projection index lookup for that container. This is the D5 fix: location
  is derived from the focused window's real ancestry, never copied from prior state.
- structural events (`window::{new,close,move}`, `workspace::{focus,init,empty}`) —
  refresh the location index from `get_tree()` (accurate ancestry), then yield the
  neutral observation. `get_tree` is confined to these (rarer) events, not fired per
  focus — so the F2 response-time race is avoided for identity, and a focus that
  doesn't restructure the tree reads a still-valid index.
- `window::{title,fullscreen_mode,urgent}`, `workspace::urgent` — incremental from
  the payload; these never move workspace/output. `output` is **retained** from the
  index across events that don't carry it (F9), mirroring today's workspace-retention.

`get_tree` and index maintenance live in the adapter (impure shell);
`focus_state_from_tree`/the location-index build and the incremental mappers stay
pure. This makes the Sway adapter a projection adapter structurally symmetric with
Niri's accumulator (D5's rationale). The exact structural-refresh trigger set is a
`/plan` completeness item (F9).

**Detection (DD10).** `select_client("auto")` resolves by connect-attempt; in SL-002
only the Sway socket is tried and `niri`/both-set resolution raises
`NotImplementedError` with a "lands in SL-003" message. `--compositor sway` is
explicit. The full D7 both-set/liveness logic is built when the second adapter
exists (SL-003) — SL-002 provides the seam, not a lie.

### 5.5 Invariants, Assumptions & Edge Cases

- **INV-1** every observation carries a `DesktopState`; the runner always writes
  current-state after each (preserving today's write-on-every-transition behaviour).
- **INV-2** `encode` is the sole writer of `source` and `producer`.
- **INV-3** neutral event names emitted by the encoder == names the deriver keys on.
  Emitted: `snapshot`, `window_focus`, `window_title`, `window_new`, `window_close`,
  `window_move`, `window_fullscreen_mode`, `window_urgent`, `workspace_focus`,
  `workspace_urgent`, `compositor_disconnected`, `compositor_reconnected`. The
  deriver's segment-close trigger accepts **both** `compositor_disconnected` and the
  legacy `sway_disconnected` (F6), for the retention window's frozen raws.
- **Edge** `focus_state_from_tree`/index lookup returning empty (no focused
  container) → empty `DesktopState` (today's behaviour, `state.py:85`), preserved.
- **Assumption** `current/sway.json`'s consumers are field-name-agnostic
  (review-001 § OQ-1: four verbatim-passthrough readers) → `con_id`→`window_id` in
  the payload is safe. Tracked as SQ1.

## 6. Open Questions & Unknowns

- **SQ1 — current-state field rename safety.** review-001 asserts the four SATAN/
  doctor readers pass `current/sway.json` through verbatim, so `con_id`→`window_id`
  is harmless. Low risk; a no-regression checkpoint, not a live re-read.
- **SQ2 — RESOLVED (F2).** The D5 mechanism is a live projection (DD6): focus
  identity from the payload, location from a `get_tree`-refreshed index. This
  complies with D5's locked choice and avoids the get_tree-per-focus race.
- **SQ3 — RESOLVED (F4/reviewer B).** The D8 segment-key change does **not** ripple
  into histograms automatically — `histogram.py::aggregate` buckets on bare
  `app_id`/`workspace` (`:54-57`). Consequence: D8's anti-conflation goal is **not**
  met at the histogram tier by the segment-key change alone. Because the conflation
  only arises with Niri's per-output unnamed workspaces (inert for Sway's
  globally-unique names), the histogram-key widening is **deferred to SL-003** where
  it becomes load-bearing, recorded as a latent defect (R4), not silently dropped —
  and it will change SATAN's `per_workspace_seconds` shape, to be coordinated there.
- **SQ4 — `panopticon-sway` wrapper home.** A retained one-file `sway_watcher/` shim
  vs a `desktop_watcher` `--compositor sway` alias. Cosmetic; decide at phase 4.

## 7. Decisions, Rationale & Alternatives

- **DD1 — `compositor/` package + `desktop_watcher/` entrypoint; `sway_watcher/`
  → wrapper.** Mirrors SPEC-001's C4 decomposition. Alt (flat `compositor.py`)
  rejected: the sway/niri split needs subpackages.
- **DD2 — `CompositorSession.observations()` yields its own snapshot first
  (pull→push inversion).** Descends D5/H2. `process_session` loses `get_tree` and its
  vestigial state threading/return (F3); the runner becomes compositor-blind. Alt
  (keep `get_tree` on the contract, Niri fakes it) rejected: Niri has no atomic tree.
- **DD3 — Model = WindowRef / DesktopState / DesktopObservation; `FocusState`
  subsumed; `to_dict` flattens to today's key set.** Preserves the `current/*.json`
  payload shape (only `con_id`→`window_id`). One focus model, not two (V6). Descends
  D4 (thin model, `output` first-class alongside `workspace`).
- **DD4 — Neutral encoder is the single `source`/`producer` injector; event
  vocabulary preserved from Sway minus the `compositor_*` rename.** Descends
  D1/D10. Adapters emit neutral observations only. Alt (each adapter builds full
  `Event`s) rejected — smears `producer` and re-opens the H4 hardcoded-source bug
  class per adapter.
- **DD5 — Emit `window_id` only (rename `con_id`; no dual-emit).** Reconciles the
  D1↔D2 surface tension: D1 renames the id field to `window_id` (a rename presupposes
  a surviving field; the spec boundary diagram shows `window_id`; firefox already
  emits it); D2/H3 drop the back-compat *dual-emit* of the legacy `con_id` name (no
  reader needs it). Net: events carry `window_id`, never `con_id`. Reviewer A judged
  this the better-supported reading; the doctrine-clean confirmation is a one-line
  spec clarification on D1/D2 (F1) — nice-to-have, not blocking; the schema fixture
  (R5) pins the emitted name regardless.
- **DD6 — D5 via a live Sway projection (comply with D5).** The adapter holds a
  `container_id → (workspace, output)` index (seeded/refreshed by `get_tree` on
  structural events) and reads focus **identity** from the event payload. Descends
  D5's locked choice ("we choose the projection") and its symmetry-with-Niri
  rationale. **Supersedes** the draft's get_tree-per-focus mechanism, which reviewer
  A showed overturns a locked decision *and* carries a response-time race (event N's
  handler observing N+1's tree; spurious segment-close if the focused container
  closed mid-round-trip). Alt (full incremental tree mirror, no `get_tree` after
  seed) rejected: Sway event payloads lack ancestry, so incremental reconstruction is
  fragile; a `get_tree`-refreshed index is robust and confines `get_tree` to rare
  structural events. Gets its own before/after test (D5 requirement).
- **DD7 — Compat side-write via a `RawStore` option** (`current/desktop.json` +
  `current/sway.json`, same payload). Descends D2 — lives in the store write path,
  not the encoder (confirmed a new mechanism is needed: `write_current` writes
  exactly one file today, V5/reviewer B). Alt (runner writes twice) rejected: leaks a
  compat concern into the neutral loop.
- **DD8 — Segmentizer: add `("desktop","focus")` to `_SOURCES`; thread `source`
  through `derive`; key → `(producer, output, app_id, workspace)`; close on
  `compositor_disconnected` **and** `sway_disconnected` (F6).** Descends D8 + H4.
  Keeping the `("sway","focus")` entry (OQ-4) is what preserves the
  `test_segmentizer_derive` `source=="sway"` equivalence (V5). Histogram-key widening
  deferred to SL-003 (SQ3/F4). The shared-`focus`-prefix segment-overwrite hazard
  (both raw sources → one `focus-DAY.jsonl`) is a **non-issue in practice** because
  Sway is dormant and writes no new raws (DD11/R3) — but the frozen historical sway
  raws are handled correctly by the dual-name close.
- **DD9 — `Backoff` **and** `IpcEvent` relocate to `compositor/`; dead `ipc.py`
  symbols retired.** V1 correction: `IpcEvent` is LIVE (imported by `runner.py` and
  `_i3ipc.py`) — it moves to `compositor/sway/project.py` (the i3ipc-facing seam) and
  `_i3ipc.py`'s import repoints; `Backoff` moves to `compositor/runner.py`. Only
  `stream`/`Ipc{Disconnected,Reconnected}`/`StreamMessage` are deleted (no production
  importer — D6). Their `test_sway_ipc` coverage is deleted; the five `Backoff` tests
  in that file **relocate** with `Backoff`, not deleted (V8).
- **DD10 — `panopticon-desktop --compositor auto|sway`; niri branch raises;
  `panopticon-sway` kept as wrapper + `nix meta.mainProgram` moves.** Descends D7.
  SL-002 builds the detection *seam* and the sway path; the both-set/liveness
  resolution and the niri path complete in SL-003.
- **DD11 — No live-stream cutover in SL-002 (resolves F5).** F5 flagged that, because
  the encoder always emits `source:"desktop"` (D1), deploying the neutral watcher
  flips the stream — which *would* drag the migration-day hazards into SL-002. The
  owner reality dissolves it: **Sway is dormant, the data is dead**
  ([[mem.fact.panopticon.niri-live-sway-dead]]). There is no live sway producer to
  collide with a new desktop stream, so the R3 segment-overwrite does not arise in
  practice and OQ-4's migration-day equivalence is low-stakes. Historical
  `raw/sway-*.jsonl` are frozen and age out within the 7-day raw retention; the F6
  dual-name close keeps their reprocessing correct meanwhile. Net: SL-002 delivers
  the capability and the schema; **live data resumes at SL-003** (Niri). SL-004 keeps
  docs + unit-name cosmetics + the compat side-write drop after SATAN repoint.

## 8. Risks & Mitigations

- **R1 — Mechanical extraction hides a real behaviour change.** Mitigation: golden
  Sway fixtures move; the *only* permitted **behaviour** delta is the D5 before/after
  test. Deliberate rename-driven assertion edits (§9) are enumerated and expected;
  any *other* diff is a red flag.
- **R2 — RESOLVED.** The DD6 live projection removes the get_tree-per-focus latency
  and response-time race entirely; `get_tree` fires only on structural events.
- **R3 — Segment-overwrite on the shared `focus` prefix.** Not triggered: Sway is
  dormant (DD11), so no new `raw/desktop-*.jsonl` collides with a live
  `raw/sway-*.jsonl`. Should Sway ever run again alongside desktop, the resolution
  (merge raws by segment-prefix before deriving) is recorded for whoever re-lives it.
- **R4 — D8's histogram de-conflation is unmet until SL-003 (F4/SQ3).** Mitigation:
  recorded as a latent defect; the histogram-key widening + the SATAN
  `per_workspace_seconds` coordination land with the Niri work where the conflation
  is real. Inert for Sway.
- **R5 — DD5 misreads the D1↔D2 id decision.** Mitigation: reviewer A judged DD5 the
  supported reading; the schema fixture pins the emitted field name so the choice is
  explicit and test-guarded; optional spec clarification (F1) makes it airtight.

## 9. Quality Engineering & Validation

**Gate (honest reframe, per reviewer B V2–V6/V8):** behaviour is preserved *modulo
the deliberate schema renames* (`con_id`→`window_id`, `sway_*`→`compositor_*`) and
the D5 fix. Suites move with their modules; assertions change **only** where a rename
or the contract shape forces it — enumerated:

- `test_sway_events.py` — `con_id`→`window_id` in emitted `fields` (`:32-37,:203`);
  event-name renames `sway_disconnected`/`sway_reconnected`→`compositor_*`
  (`:215,:222`).
- `test_sway_runner.py` — **rewrite**, not an import edit: the `FakeSession`
  (`get_tree()`+`events()`, `:73-83`) becomes a fake `CompositorSession`
  (`observations()`); the disconnect/reconnect event-name rows (`:181-186,:211-218`)
  update; `_read_lines` reads `raw/desktop-*.jsonl`, not `sway-*.jsonl` (`:111`).
- `test_segmentizer_derive.py` — the `disc()` helper (`:41`) and the disconnect-close
  test update for the dual-name trigger; `source=="sway"` (`:65`) survives via the
  kept `("sway","focus")` entry (V5).
- `test_sway_state.py` — updates as `FocusState` is subsumed by `DesktopState`
  (`.con_id`→`window_id`; `:112-119,:150`) (V6).
- `test_sway_ipc.py` — the `stream`/`Ipc*` tests are deleted with the dead code; the
  five `Backoff` tests relocate with `Backoff` (V8).

**Positive tests:**
- **D5 before/after test:** a focus change crossing a workspace/output boundary
  asserts the *new* (correct) workspace/output via the projection, with the prior
  (buggy) expectation recorded in a behaviour-change note — isolating the intentional
  change from extraction drift.
- **Schema fixture:** a `source:"desktop"`, `producer:"sway"`, `window_id` sample
  round-tripped through `schema.from_dict` and the neutral encoder — pins DD4/DD5.
- **Encoder unit tests:** observation → Event mapping (source/producer injection,
  compact fields, the `compositor_*` names, per-event field preservation F8).
- **Segmentizer equivalence:** a Sway raw corpus (carrying the legacy
  `sway_disconnected`) produces equivalent `focus-DAY.jsonl` under the dual-name
  close — proving the deriver change preserves behaviour for historical Sway input.
- **Runner tests:** `process_session` drives a fake `CompositorSession` (snapshot-
  first, deltas, EOF); `run_watcher` reconnect emits the neutral disconnect/reconnect
  pair. Reuses today's fake-session pattern (no live compositor).

TDD red/green/**refactor** per phase; `just check` (lint zero-warning + test +
format) before every commit.

## 10. Review Notes

Adversarial review 2026-07-17 (two reviewers: design decisions + code-surface).
Verdict on the draft: **not lockable as-is**; two blocking items, now resolved.

- **F2 (blocking) — RESOLVED:** DD6 rewritten to comply with locked D5 (live
  projection; identity-from-payload, location-from-`get_tree`-refreshed-index),
  removing the draft's locked-decision overturn and its response-time race.
- **F5 (blocking) — RESOLVED (DD11):** the deployment-boundary contradiction is
  dissolved by the owner reality — Sway is dormant, data is dead, so there is no
  live-stream cutover; the migration-day hazards do not arise in practice. Live data
  resumes at SL-003.
- **F4/F6 (should-fix) — FOLDED:** histogram de-conflation deferred to SL-003 with a
  recorded latent defect (R4/SQ3); the deriver closes on both the legacy and neutral
  disconnect names (INV-3/DD8).
- **F1/F3/F7/F8/F9 (notes) — FOLDED:** DD5 reading confirmed (optional spec
  clarification); `process_session` return dropped as vestigial; the phase seam is
  "phase-1 green against **fakes**, not a live-Sway shim" (below); per-event `fields`
  preserved verbatim, only `state` re-derived; `output` retained across events that
  don't carry it (a `/plan` completeness item).
- **V1–V8 (code-surface) — FOLDED:** `IpcEvent` relocation (DD9), the §9 gate reframe
  and its enumerated assertion changes, `Backoff` tests relocate not delete,
  `FocusState` subsumed, and the confirmed anchors/deletions.

**Open for the `/plan` stage (not lock blockers):**
- **Phase seam (F7):** phase 1 (model + encoder + neutral runner + `Backoff`) ships
  green against a **fake** `CompositorSession`; the real Sway adapter (live
  projection + D5) is phase 2. There is no coherent "Sway through a thin shim" for
  phase 1 — any shim adapting today's `get_tree`+`events` to `observations()` *is*
  the phase-2 adapter. `/plan` should define phase-1 greenness against fakes.
- **F9 completeness:** the exact structural-event set that refreshes the projection
  index, and the deriver's `output` retention across events lacking it.
- **SQ1:** the `current/sway.json` field-rename no-regression checkpoint before
  phase 3 flips the payload.

The design is **lockable** with F2/F5 resolved and F4/F6 folded (both reviewers'
condition for lock).
