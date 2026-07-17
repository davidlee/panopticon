# Design SL-002: Compositor-neutral core and Sway migration

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SPEC-001, SL-003); doc-local refs bare — spec decisions D1..D11, spec open
     questions OQ-1..OQ-5, this design's decisions DD1..DD10, questions SQ1..,
     risks R1.. -->

Descends from SPEC-001 (`references --role implements`). SPEC-001 locks the
container-level decisions (D1–D11) and closed OQ-1/OQ-3; this design descends them
to the module/function level for the first two of the slice family's phases-worth of
change: **stand up the neutral core and move Sway behind it, emitting the migrated
`source:"desktop"` schema, behaviour-preserving bar the D5 focus fix.** Niri is
SL-003; operational cutover is SL-004.

## 1. Design Problem

`panopticon.sway_watcher` is Sway-shaped end to end: the runner pulls one atomic
`get_tree()` snapshot, the encoder hardcodes `make_event("sway", …)`, and the
segmentizer keys and closes on Sway-specific values. A second compositor (Niri,
SL-003) cannot ride this. This slice extracts a compositor-neutral core — model,
runner, event encoder, adapter contract, entrypoint/detection — and re-expresses
Sway as the first adapter behind it, **without regressing the existing Sway
behaviour** except the one deliberate D5 fix, and **emitting the final migrated
schema from the start** (SPEC-001 review correction 1) so downstream fixtures land
once rather than being rewritten by SL-003.

The load-bearing risk: the neutral contract shape. Get the `CompositorSession`
boundary wrong and SL-003/SL-004 inherit a Sway-shaped core. The single most
important call is the **pull→push inversion** (D5/H2): the contract must let each
adapter yield its *own* initial snapshot, so `process_session` never calls
`get_tree` and Niri's terminator-less burst fits the same seam as Sway's atomic pull.

## 2. Current State

Verified against the tree (2026-07-17). Files this slice restructures:

- `sway_watcher/runner.py` — `process_session` (`:55-83`) pulls `get_tree()`
  (`:68`), derives `focus_state_from_tree` (`:69`), emits `snapshot` (`:72`), writes
  `current/sway.json` (`:73`), then streams `transform`ed events (`:74-81`).
  `run_watcher` (`:86-121`) owns reconnect/backoff and emits the synthetic
  `sway_reconnected` (`:109`) / `sway_disconnected` (`:119`) events. `AsyncSession`
  (`:40-45`) is the leak: `events()` **and** `get_tree()`.
- `sway_watcher/events.py` — pure `transform` (`:33-43`); eight `make_event("sway",
  …)` call sites (`:84,110,136,173,186,194,199,203`); the D5 bug at `_on_window_focus`
  (`:76-83`) copying `workspace`/`output` from prior state.
- `sway_watcher/state.py` — `FocusState` (`:19-38`, carries `con_id`),
  `app_id_from_container` (`:41-51`), `find_focused` (`:54-66`),
  `ancestor_name_of_type` (`:69-78`), `focus_state_from_tree` (`:81-98`) — the pure
  tree projection that derives workspace/output **correctly** via ancestry.
- `sway_watcher/ipc.py` — `Backoff` (`:60-88`, LIVE) + `IpcEvent` (`:37-42`, LIVE)
  alongside the DEAD `stream()`/`Ipc{Disconnected,Reconnected}`/`StreamMessage`
  (`:45-57,94-138`) — the D6 duplication.
- `sway_watcher/_i3ipc.py` — the only `i3ipc` importer; queue-bridge session.
- `sway_watcher/__main__.py` — `panopticon-sway`; `--source` default `"sway"`
  (`:33-37`); `RawStore(args.source, …)` (`:61`).
- `store.py` — `RawStore` already source-parameterized: `raw/{source}-{day}.jsonl`
  (`:41`), `current/{source}.json` (`:45`), atomic `write_current` (`:56-67`).
- `schema.py` — `Event{v,ts,source,event,fields}`; `from_dict` validates *shape*
  only, no `source`/`event` value checks (`:56-69`); `make_event(source, event, …)`.
- `segmentizer/__main__.py` — `_SOURCES` (`:36-39`); per-source loop `:59-77`;
  `seg_path` overwrites per `(seg_prefix, day)` (`:73-76`). `derive` called without a
  `source` arg (`:72`) → falls to its `"sway"` default.
- `segmentizer/derive.py` — `derive_segments(source="sway", …)` (`:32-37`); focus key
  `(app_id, workspace)` (`:69-74`); segment body stamps `source` (`:106`); closes on
  literal `"sway_disconnected"` (`:82`).
- `segmentizer/retention.py` — `_SEGMENT_PREFIX_FOR_RAW` (`:26-29`);
  `_source_from_raw_name` already generic (`:93-98`); optimistic-fallback reap
  (`:101-108`) — the OQ-4 hazard site.

Out-of-repo readers of `current/sway.json` (SPEC-001 D2/OQ-1, read-only, **not**
edited here): four verbatim-passthrough sites in SATAN + the sleipnir doctor.

## 3. Forces & Constraints

- **Behaviour preservation (gate).** Existing Sway suites are the proof. They move
  with their modules (import paths change — mechanical), assertions unchanged except
  the one documented D5 before/after delta. `just check` green each phase.
- **Purity split.** Native decode, tree projection, observation construction, and
  event encoding stay pure/unit-testable. `get_tree`, sockets, reconnect, backoff,
  disk live in the async shell (the adapter session + runner).
- **Schema-once (review correction 1).** Emit `source:"desktop"` + `producer` +
  `window_id` from the first phase, so SL-003 adds a producer value, not a reshape.
- **Compat surface is exactly one file** (D2): `current/sway.json` side-write. No
  other back-compat carried; `con_id` dropped, not dual-emitted (H3).
- **Encoder ↔ deriver lockstep.** The segment deriver keys on literal event names
  (H4). Renaming `sway_disconnected`→`compositor_disconnected` in the encoder and
  updating `derive.py`'s close-trigger must land in the **same** slice — they are one
  contract split across two files.
- **Single-adapter honesty.** Niri is out of scope; the detection/CLI *structure*
  must admit a second adapter (SL-003) without the SL-002 code pretending Niri
  exists — a `niri` branch that raises, not a stub that lies.

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
    project.py   FocusState/tree-walk helpers (from state.py) + focus_state_from_tree
    session.py   CompositorSession over i3ipc: get_tree projection + D5 fix + neutral obs
    _i3ipc.py    i3ipc CompositorClient (moved verbatim)
desktop_watcher/
  __main__.py  panopticon-desktop --compositor auto|sway ; wires client→runner→store
```

`sway_watcher/` collapses to a thin `panopticon-sway` compatibility wrapper (DD10).

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
async def process_session(session, store, producer) -> DesktopState:
    async for obs in session.observations():        # first obs is the snapshot
        ev = encode(obs, producer)                  # source:"desktop", producer, window_id
        store.write(ev)
        store.write_current(obs.state.to_dict())    # current/desktop.json (+ sway.json compat)
    return <last obs.state>
```

`run_watcher` keeps the reconnect/backoff loop and remains the emitter of the
lifecycle events — now neutral: `compositor_reconnected` on a non-first connect,
`compositor_disconnected` on drop, both via `encode`. The fresh session supplies the
post-reconnect snapshot (D3(c) — the neutral snapshot + disconnect pair matches Sway
and will match Niri).

### 5.3 Data, State & Ownership

- **WindowRef** — `{window_id, app_id, pid, title}` (all optional). `window_id` is
  the renamed `con_id` (DD5); scoped-unique per D11.
- **DesktopState** — `{window: WindowRef | None, workspace, output}`. `to_dict()`
  **flattens** to `{window_id, app_id, pid, title, workspace, output}` — the exact
  key set today's `FocusState.to_dict` writes, `con_id`→`window_id`. This is the
  `current/desktop.json` (and compat `current/sway.json`) payload.
- **DesktopObservation** — `{event: str, fields: dict, state: DesktopState}`. Neutral
  and producer-agnostic; `fields` already `_compact`ed. `encode` adds `source` +
  `producer`. Snapshot is `event="snapshot"`; there is no separate snapshot type.
- Ownership: the adapter owns native projection + observation construction; the
  neutral encoder owns schema shape; the store owns files; the runner owns the
  connect/reconnect lifecycle and the two lifecycle events.

### 5.4 Lifecycle, Operations & Dynamics

**Sway adapter session (DD6, the D5 fix).** On connect: `get_tree()` →
`focus_state_from_tree` → yield the `snapshot` observation. Then per i3ipc event:

- `window::focus` and `workspace::focus` (the workspace/output-affecting events):
  re-`get_tree()` and re-derive via `focus_state_from_tree`, then yield the neutral
  observation. This **is** the D5 fix — workspace/output come from the freshly
  focused window's ancestry, never copied from prior state — and it reuses the pure
  snapshot projection unchanged, so the focus path and the snapshot path become the
  same derivation.
- `window::{title,new,close,move,fullscreen_mode,urgent}` and `workspace::urgent`:
  incremental update from the payload (no tree needed — these never move
  workspace/output), yield the neutral observation, mirroring today's `transform`.

`get_tree` calls stay inside the adapter (impure shell); `focus_state_from_tree` and
the incremental mappers stay pure.

**Detection (DD10).** `select_client("auto")` resolves by connect-attempt; in SL-002
only the Sway socket is tried and `niri`/both-set resolution raises
`NotImplementedError` with a "lands in SL-003" message. `--compositor sway` is
explicit. The full D7 both-set/liveness logic is built when the second adapter
exists (SL-003) — SL-002 provides the seam, not a lie.

### 5.5 Invariants, Assumptions & Edge Cases

- **INV-1** every observation carries a `DesktopState`; the runner always writes
  current-state after each (preserving today's write-on-every-transition behaviour).
- **INV-2** `encode` is the sole writer of `source` and `producer`.
- **INV-3** neutral event names emitted by the encoder == names the deriver keys on
  (lockstep). Enumerated: `snapshot`, `window_focus`, `window_title`, `window_new`,
  `window_close`, `window_move`, `window_fullscreen_mode`, `window_urgent`,
  `workspace_focus`, `workspace_urgent`, `compositor_disconnected`,
  `compositor_reconnected`.
- **Edge** `focus_state_from_tree` returning empty (no focused container) → empty
  `DesktopState` (today's behaviour, `state.py:85`), preserved.
- **Assumption** `current/sway.json`'s consumers are field-name-agnostic
  (review-001 § OQ-1: four verbatim-passthrough readers) → `con_id`→`window_id` in
  the payload is safe. Tracked as SQ1.

## 6. Open Questions & Unknowns

- **SQ1 — current-state field rename safety.** review-001 asserts the four SATAN/
  doctor readers pass `current/sway.json` through verbatim, so `con_id`→`window_id`
  is harmless. Low risk; confirm no reader dereferences `con_id` by name before phase
  3 flips the payload. (Not a live re-read of SATAN — the review already inventoried
  it; this is a "no regression" checkpoint.)
- **SQ2 — D5 mechanism: get_tree-per-focus vs a live incremental projection.** DD6
  proposes re-`get_tree` on focus/workspace-focus events. Cheaper than a full
  incremental Sway tree projection and reuses pure code, at the cost of one IPC
  round-trip per focus change (ms, at human focus rates) and a small tree-moved-under-
  us race window (strictly better than copying stale state). **Recommended;** the
  adversarial review should stress whether D5's "live projection" wording forbids
  this. See DD6.
- **SQ3 — D8 key ripple into histograms + SATAN.** Adding `(producer, output)` to the
  focus segment key/record changes `focus_segment` bodies and the histogram
  aggregation key. `satan-percept.el:190-204` reads `app_id`/`workspace`/`last_title`
  from focus *segments* (additive keys are ignored → safe), but histogram *shape* may
  change. Read `segmentizer/histogram.py` + confirm the histogram consumer at
  `/plan`; may widen phase 3.
- **SQ4 — `panopticon-sway` wrapper home.** A retained one-file `sway_watcher/`
  shim vs a `desktop_watcher` `--compositor sway` alias. Cosmetic; decide at phase 4.

## 7. Decisions, Rationale & Alternatives

- **DD1 — `compositor/` package + `desktop_watcher/` entrypoint; `sway_watcher/`
  → wrapper.** Mirrors SPEC-001's C4 decomposition. Alt (flat `compositor.py`)
  rejected: the sway/niri split needs subpackages.
- **DD2 — `CompositorSession.observations()` yields its own snapshot first
  (pull→push inversion).** Descends D5/H2. `process_session` loses `get_tree`; the
  runner becomes compositor-blind. Alt (keep `get_tree` on the contract, Niri fakes
  it) rejected: Niri has no atomic tree — the leak SPEC-001 H2 identifies.
- **DD3 — Model = WindowRef / DesktopState / DesktopObservation; `DesktopState.
  to_dict` flattens to today's key set.** Preserves the `current/*.json` payload
  shape (only `con_id`→`window_id`), so the compat file stays consumable. Descends
  D4 (thin model, `output` first-class alongside `workspace`).
- **DD4 — Neutral encoder is the single `source`/`producer` injector; event
  vocabulary preserved from Sway minus the `compositor_*` rename.** Descends
  D1/D10. Adapters emit neutral observations only. Alt (each adapter builds full
  `Event`s) rejected — smears `producer` and re-opens the H4 hardcoded-source class
  of bug per adapter.
- **DD5 — Emit `window_id` only (rename `con_id`; no dual-emit).** Reconciles the
  apparent D1↔D2 tension: D1 renames the id field to `window_id`; D2/H3 drop the
  *back-compat dual-emit* of the legacy `con_id` name (no reader needs it). Net:
  events carry `window_id`, never `con_id`. **Flagged for review** — this is my
  reading of two decisions that touch the same field; if D2's "con_id removed from
  the raw tier" means *no id field at all*, DD5 is wrong and the id is dropped
  entirely. (Leaning emit-`window_id`: D1 states the rename explicitly, the schema
  overview shows `window_id`, firefox already uses it, and it is near-free.)
- **DD6 — D5 via get_tree-per-focus, reusing `focus_state_from_tree`.** See SQ2.
  Chosen over a live incremental Sway tree projection: the incremental reconstruction
  is complex and error-prone for no benefit at focus frequency, and re-projecting
  from the tree makes the focus path identical to the snapshot path (one code path,
  one test surface). **Flagged** — narrows D5's "live projection" to "re-project on
  the events that can move workspace/output," which I argue is the same intent
  (adapter holds state, derives from the tree, not from prior neutral state) at lower
  cost. Gets its own before/after test (D5 requirement).
- **DD7 — Compat side-write via a `RawStore` option** (`current/desktop.json` +
  `current/sway.json`, same payload). Descends D2 — lives in the store write path,
  not the encoder. Alt (runner writes twice) rejected: leaks a compat concern into
  the neutral loop.
- **DD8 — Segmentizer: add `("desktop","focus")` to `_SOURCES` **keeping**
  `("sway","focus")`; thread `source` through `derive`; key →
  `(producer, output, app_id, workspace)`; close on `compositor_disconnected`.**
  Descends D8 + H4 + OQ-4 (keep the sway entry alive). The shared-`focus`-prefix
  segment-overwrite hazard (both sources write `segments/focus-DAY.jsonl`) only bites
  when *both* raw streams hold the same day — which happens at operational cutover,
  **SL-004's** concern (R3). In SL-002 the deployed producer is still Sway; the
  desktop pipeline is added, not yet fed.
- **DD9 — `Backoff` moves to `compositor/runner.py`; dead `ipc.py` retired.**
  Descends D6; `test_sway_ipc.py`'s coverage of `stream`/`Ipc*` is deleted with the
  code (no production importer).
- **DD10 — `panopticon-desktop --compositor auto|sway`; niri branch raises;
  `panopticon-sway` kept as wrapper + `nix meta.mainProgram` moves.** Descends D7.
  SL-002 builds the detection *seam* and the sway path; the both-set/liveness
  resolution and the niri path are completed in SL-003 when there is a second socket
  to disambiguate.

## 8. Risks & Mitigations

- **R1 — Mechanical extraction hides a real behaviour change.** Mitigation: golden
  Sway fixtures move unchanged; the *only* permitted assertion delta is the D5
  before/after test (DD6). Any other diff is a red flag.
- **R2 — get_tree-per-focus latency/race (DD6/SQ2).** Mitigation: `get_tree` is
  millisecond-scale and focus events are human-paced; re-projection is strictly more
  correct than the status quo. Revisit only if measured latency bites.
- **R3 — Segment-overwrite on the shared `focus` prefix at cutover.** Not triggered
  in SL-002 (Sway is still the live producer). Mitigation: hand to SL-004 with a
  named resolution candidate (merge raws by segment-prefix before deriving, or a
  dated sway-entry retirement) + a migration-day equivalence test (SPEC-001 OQ-4).
- **R4 — D8 histogram-schema change reaches a histogram consumer.** Mitigation: SQ3
  — read `histogram.py` and confirm consumer tolerance at `/plan` before touching the
  focus segment schema; keep additive where possible.
- **R5 — DD5 misreads the D1↔D2 id decision.** Mitigation: flagged for adversarial
  review; schema fixture pins the emitted field name so the choice is explicit and
  test-guarded.

## 9. Quality Engineering & Validation

- **Behaviour-preservation gate:** the full existing Sway suite green after each
  phase (imports updated to `compositor.sway.*`; assertions unchanged bar D5).
- **D5 before/after test:** a focus change crossing a workspace/output boundary
  asserts the *new* (correct) workspace/output, with the prior (buggy) expectation
  recorded in a behaviour-change note — isolating the intentional change from
  extraction drift.
- **Schema fixture:** a `source:"desktop"`, `producer:"sway"`, `window_id` sample
  round-tripped through `schema.from_dict` and the neutral encoder — pins DD4/DD5.
- **Encoder unit tests:** observation → Event mapping (source/producer injection,
  compact fields, the `compositor_*` names).
- **Segmentizer equivalence:** the same Sway raw corpus produces equivalent
  `focus-DAY.jsonl` before and after threading `source` + the D8 key (accounting for
  the added `producer`/`output` fields) — proving the deriver change is behaviour-
  preserving for Sway input.
- **Runner tests:** `process_session` drives a fake `CompositorSession` (snapshot-
  first, deltas, EOF); `run_watcher` reconnect emits the neutral disconnect/reconnect
  pair. Reuses today's fake-session pattern (no live compositor).
- TDD red/green/**refactor** per phase; `just check` (lint zero-warning + test +
  format) before every commit.

## 10. Review Notes

Adversarial review targets (the design-rhythm second pass, per the core process):
- **DD2/DD6** — is the pull→push contract right, and does get_tree-per-focus honour
  D5's intent, or must the Sway adapter hold a live incremental projection? (SQ2)
- **DD5** — the D1↔D2 `window_id`/`con_id` reconciliation. Is the id emitted or
  dropped outright? (the one place two locked decisions touch the same field)
- **DD8/R3/R4** — the segment-tier blast radius: shared-prefix overwrite ownership
  (SL-002 vs SL-004) and the D8 histogram ripple (SQ3).
- **Phase seam** — is "neutral core" (phase 1) genuinely shippable green with Sway
  wired through a thin shim before the Sway adapter is fully relocated (phase 2), or
  do phases 1–2 collapse into one? (a `/plan` question this design should not
  pre-empt, but the review should sanity-check the seam exists.)
