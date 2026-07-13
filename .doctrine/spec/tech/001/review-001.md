# SPEC-001 adversarial review (derived — regenerable synthesis)

Three parallel adversarial reviewers, 2026-07-13:
- **A** — falsify H1–H5 / coupling map against live code.
- **B** — verify Niri protocol claims against niri-ipc authoritative sources.
- **C** — attack decisions D1–D7 + the 7-slice sequence.

Verdict: **protocol section is sound; the domain/runner model and H4 need
revision before slices are cut.** No decision is fatally wrong; five need
rework. Two are genuine forks for the project owner (marked ⚑).

## Confirmed as-authored (no change)
- **H3** — `con_id` has no in-repo downstream consumer. CONFIRMED (segmentizer
  keys `(app_id, workspace)` only; derive/retention/browser/histogram never read
  it). Nuance: read *inside the producer* at events.py:123 for close-detection.
- **D5 bug is real** — events.py:81-82 copies workspace/output from prev state;
  `focus_state_from_tree` (state.py:81-98) derives correctly via ancestry.
- **D6 dead code** — `stream()`/`Ipc*`/`StreamMessage` production-dead; only
  `Backoff`+`IpcEvent` live. CAVEAT: test_sway_ipc.py exercises them — deleting
  the code deletes that test too.
- **Store param (D1)** — `raw/{source}-*.jsonl`, `current/{source}.json` are pure
  f-strings; new names fall out automatically. CONFIRMED.
- **Niri protocol (H1/D3)** — framing (`"EventStream"` → `{"Ok":"Handled"}` →
  NDJSON), event variant names/payloads, Window (no `output`, `workspace_id`
  optional), Workspace (`output`/`is_active`/`active_window_id`), additive-only
  stability guarantee: all CONFIRMED against rustdoc + wiki + lib.rs.
- **niri-ipc v26.4.0** exists, is the *current latest* (published 2026-07-10),
  and the crate is deliberately not semver-stable → exact `=` pin is required,
  not optional. **OQ-3 can close**: `Timestamp{secs,nanos}` and `WindowLayout`
  (geometry) are irrelevant to a focus/title/workspace/output watcher.

## Corrections to fold in (no fork — clear fixes)
1. **H2 undercounts the runner leaks / mis-frames the model.** Beyond `get_tree`
   + `transform`: `focus_state_from_tree` parse (runner.py:69), three synthetic
   `source="sway"` event factories (snapshot/reconnected/disconnected, :72/109/119
   → events.py:194/199/203), logger `"panopticon.sway"` (:37), `AsyncSwayClient`
   (:49). **Deeper (A+C agree):** `process_session` (runner.py:67-73) is *pull*-
   shaped — atomic `get_tree()` → snapshot. Niri is *push* — state arrives across
   `WindowsChanged`/`WorkspacesChanged`/`WindowFocusChanged` with no terminator.
   You cannot "delete the leak": Sway needs the pull, Niri can't provide it. The
   neutral contract must invert to *the adapter yields its own initial `snapshot`
   observation* (Sway calls get_tree internally; Niri accumulates the burst), and
   `process_session` stops calling get_tree at all. Reword H2.
2. **Niri id reuse (B).** "IDs reusable after close" is NOT documented — lib.rs
   guarantees stability only while open and refuses ordering/start guarantees.
   Reword to "opaque u64, stable only while the window is open; assume nothing
   about ordering or cross-lifetime reuse." Novelty test still valid (WindowClosed
   removes id first). Burst cross-category order is also not guaranteed — projection
   must stay order-independent (it is).
3. **D3 missing failure rules.** Specify: (a) burst-completion rule — buffer until
   first `WindowFocusChanged`; absence → incomplete session, discard, don't emit
   snapshot; (b) `WindowFocusChanged{id:None}` (overview / all-closed) maps to a
   defined neutral state the deriver treats as *continuation*, NOT segment-close —
   else overview toggling flaps the segment stream (a failure Sway lacks);
   (c) emit neutral snapshot + compositor_disconnected on every reconnect so the
   deriver's close/reopen matches Sway.
4. **D7 both-set + liveness.** auto-detect must define both-NIRI_SOCKET-and-SWAYSOCK
   resolution (don't leave it implicit in list order) and treat env-var presence as
   a hint validated by an actual connect, not ground truth (stale SWAYSOCK from a
   dead session). "Fail clearly" only covers neither-set today.
5. **Historical-data reaping hazard (slice sequence).** On migration day the state
   dir holds both `raw/sway-*.jsonl` and `raw/desktop-*.jsonl`, and sway raws stay
   in the 7-day retention window. If the `sway` entry is *replaced* (not kept) in
   `_SOURCES` (__main__.py:36-39), the segmentizer stops globbing sway raws, yet
   the reaper's optimistic fallback (retention.py:105-108) still deletes them →
   **un-segmented data silently reaped.** Keep `sway` segmentizer/retention entries
   alive on a retirement *dated to raw retention*, decoupled from the D2 compat drop.
   Add a migration-day equivalence test. (retention `_source_from_raw_name` is
   already generic → the spec over-listed it as needing a change.)
6. **Missing decisions to author:** timestamp source (Sway = emit/receive time via
   `utc_now_iso`; decide Niri ignores its own `Timestamp` and uses emit time too,
   else `duration_s` semantics diverge); title-change diff rule (`WindowOpenedOrChanged`
   fires on any mutation incl. resize/move — adapter must diff the `title` field and
   emit nothing for geometry mutations, else spam or drop); Niri test-fixture capture
   method + version-pin (unmitigated H1 risk at the test layer).

## ⚑ Forks for the project owner

### ⚑F1 — D1 discriminator: `source:"desktop"`+`producer` vs sibling sources
C's strongest attack: `source:"sway"|"niri"` gives `raw/sway-*.jsonl` /
`raw/niri-*.jsonl` for free with ZERO store/segmentizer/retention change, and
`producer` becomes redundant. `source:"desktop"` only buys a single downstream
stream name — but H3 shows no in-repo consumer keys on `source` beyond the
registries you're editing anyway. The whole D1 blast radius exists to serve a
downstream the spec hasn't shown exists. Counter: a single `desktop` stream is
cleaner IF an out-of-repo consumer wants "attention regardless of compositor"
(unknown until OQ-1). **Decision needed before slice 1** (it defines the encoder
contract).

### ⚑F2 — H4 is false at the data layer; segment key can't disambiguate
Both A and C: the segment *pipeline* is neutral but the *data* is not.
- A: `derive.py:35` hardcodes `source:"sway"` into every segment body; `derive.py:82`
  closes segments only on the literal event name `"sway_disconnected"` — an implicit
  event-name API in the segment tier that H4 denies exists. Rename the disconnect
  event and segments silently stop closing on compositor restart.
- C: `derive.py:69-74` keys `(app_id, workspace)`. Niri workspaces are per-output,
  dynamic, usually UNNAMED (`Workspace.name: Option`); two distinct Niri workspaces
  (outA idx1, outB idx1) collapse to the same neutral `"1"` and collide in the key.
  XWayland app_id also differs (Sway `window_properties.class` vs Niri via
  xwayland-satellite). → histograms conflate / double-count across a compositor
  switch. The neutral `workspace` model is simultaneously too thin (drops per-output
  dimension) and secretly Sway-shaped (assumes global unique workspace name). Output
  is *probably* the DRM connector name for both, but the spec never asserts it.
**Decision needed:** (a) add `producer` (and/or `output`) to the segment key;
(b) accept per-compositor-era histograms and document it; or (c) defer with a
recorded risk. Plus author an explicit decision that `output` = DRM connector name
for both producers (verify against live Niri). Reframes D4 + downgrades H4.

## Recommended path
- Resolve **OQ-1 now** (bounded read of the out-of-repo HM module + SATAN reader) —
  it collapses both D2 and ⚑F1. If no reader: drop D2, and ⚑F1 leans to the simpler
  sibling-source cut.
- Decide ⚑F1 + ⚑F2, fold corrections 1–6, close OQ-3, reword H2/H4/H1-ids.
- Re-frame D5: isolate the focus-fix as its own slice with a before/after test, OR
  state explicitly in D5 that the Sway adapter moves to a tree-projection model as
  the fix mechanism (removing the "incidental bug fix" framing — it is load-bearing:
  the fix needs the tree at focus time, i.e. per-focus get_tree or a live projection).
- THEN cut the slice family (fold schema/D1 into slice 1 so slice-2 fixtures land
  once, instead of being rewritten by slice 3).
</content>
</invoke>
