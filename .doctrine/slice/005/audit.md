# Audit SL-005: Umbriel adapter

Hand-authored (no `slice audit` scaffold yet — known CLI gap). Verification of the
completed implementation against the design (`design.md`, esp. §10 RV-005 ledger)
and the plan's EX/VT criteria. Method: `/code-review` of the branch diff
(`git diff d238133~1..HEAD`, 17 files, +1397/-31) + line-by-line conformance of
each RV item and each VT test against the code it claims to lock.

- **Auditor:** claude (opus-4-8), 2026-09-23.
- **Gate at HEAD:** `just check` green — **378 passed, 3 skipped, ruff clean.**
- **Commits:** `d238133` (PHASE-01), `8435580` (PHASE-02), `27e504d` (PHASE-03),
  `e4d4c13` (notes fix).

## Verdict

**PASS — ready to reconcile + close.** The RV-005 ledger is fully discharged *in
code*, not merely in prose; all EX/VT criteria are met by non-tautological tests;
the behaviour-preservation gate holds. One non-gating item outstanding (**VH-1**,
live-host acceptance — david's to run). Two cosmetic doc nits noted below, neither
blocking.

## RV-005 ledger closure (design §10 — the acceptance bar)

Each item walked against the shipped code, not the prose.

| item | sev | disposition | discharged in code |
|---|---|---|---|
| RV-005.1 | BLOCKER | shared `diff_state`, window-identity-wins precedence (ISS-001) | `session.py:95` calls the shared `compositor/diff.py::diff_state`; **proven end-to-end** by `test_capture1_..._attributes_the_new_app` — real capture-1 replayed through `derive_segments` yields `[ghostty, discord, emacs, discord, emacs]`, explicitly asserting *not* all-ghostty (the old mis-attribution). ✅ |
| RV-005.2 | MAJOR | coherence hold (withhold+fold), fail-**safe** raise→reburst | `session.py:78-98` — live-only hold via `proj.focus_coherent`; baseline `state` not advanced during hold; **fixed** `hold_until` deadline set once (`:89-91`) then `asyncio.timeout_at(hold_until)` (`:83`) bounds the whole multi-event hold. Timeout raises (only `StopAsyncIteration` is caught) → disconnect. Tests: `..._hold_emits_one_window_focus_with_resolved_label` (label `"mail"`, never None/`"99"`), `..._same_window_moved...is_workspace_focus` (DL-7 precedence), `..._coherence_timeout_raises_with_no_workspace_none_emit` (asserts only `["snapshot"]` leaked + `TimeoutError`). ✅ |
| RV-005.3 | MAJOR | Tier-2 overclaim → downgraded to *untested*; capture-or-accept gate | `notes.md` §PHASE-01 records **ACCEPTED LIMITATION** (umbriel unreachable in-jail); public note landed in `docs/schema.md` "Known limitation (umbriel layer-surface focus)". `>1 active` (ASM-U1) → Tier-2 fallthrough, tested (`test_more_than_one_active_falls_through_tier1`); scratchpad `active:false` neither-tier, tested. Not silently dropped. ✅ (recorded, not fixed — correct disposition) |
| RV-005.4 | MAJOR | widen `WindowRef.window_id` → `int\|str\|None` (DL-6) | `model.py:32` widened; `docs/schema.md` note added; `test_window_id_accepts_str_and_round_trips` asserts verbatim round-trip (no int coercion). ✅ |
| RV-005.5a | MAJOR | burst-completion timeout raises | `session.py:66` `asyncio.timeout(burst_timeout)` wraps the whole burst loop (frames' own `connect_timeout` bounds only connect+first read). `test_one_family_then_silent_raises_on_burst_timeout` uses a real hang-socket. ✅ |
| RV-005.5b | — | runner reconnect-ordering | **DEFERRED** (pre-existing shared runner+niri concern) — see backlog note §"carried forward". Correctly out of scope. ✅ (disposition, not fix) |
| RV-005.6 | MINOR | probe order + derived-socket eligibility (DL-8) | `detect.py:48-80` fixed order niri>sway>umbriel; `_umbriel_auto_socket` (`:144`) gates the derived path on both env vars; explicit-umbriel unresolvable → actionable `RuntimeError` (`:187-193`). Tests cover tie-break, ineligibility (with a `_umbriel_boom` guard proving umbriel is *never probed*), and the explicit-error path. ✅ |
| RV-005.7 | MINOR | non-positive pid → None, bool excluded (DL-9) | `projection.py:184` `type(p) is int and p > 0`; `test_pid_normalises_non_positive_and_bool` covers `-1/0/None/True/False`. ✅ |
| RV-005.8 | MINOR | reconcile PROVENANCE + add umbriel producer | `PROVENANCE.md` fully de-staled to DL-4 (explicitly states the pre-spike join-primary guess was *reversed*); `docs/schema.md` lists `umbriel` producer + opaque-string `window_id`. ✅ |

**All RV items discharged.** The two BLOCKER/MAJOR fail-safe hazards the 3rd
(narrow) review pass caught — the coherence-timeout fail-open and the
`window_focus` overclaim — are both correctly resolved: the timeout is fail-**safe**
(raise→reburst, no `workspace=None` live emit escapes) and the guarantee is "one
*precedence-correct* observation" (window_focus on identity change, workspace_focus
on same-window move), both directly tested.

## Objective gates (doctrine tooling)

Beyond the manual review, the CLI's own gates were run (after seeding the
source-delta registry — `record-delta --commit` per phase: PHASE-01=`d238133`,
PHASE-02=`8435580`, PHASE-03=`27e504d` — since the phases were executed solo
without delta binding; the registry is runtime/regenerable from that map):

- **`slice verify-vt SL-005` — all 13 VT criteria PASS** (attributable: each VT's
  `test_file`/`keywords`/`patterns` matched within the owning phase's delta). Exit 0.
- **`slice conformance SL-005`** — **8/8 design-target source paths conformant,
  0 undelivered.** The implementation touched exactly the surface design §3
  declared (`umbriel/**`, `detect.py`, `model.py`, `__main__.py`, `schema.md`) —
  no scope creep. The 9 "undeclared" paths are all test files + `notes.md`, the
  expected TDD/doctrine accompaniment (conformance is a design-target-only
  cross-check; tests were declared `scope-relevant`, not targets). Exit 0.
- **`slice selector doctor SL-005` — healthy, no findings** (no uncompilable /
  unmatched / redundant / broad selectors).
- Selectors were authored at close from the design §3 surface (the mechanism
  postdates the slice's execution) — committed in `slice-005.toml`.

## Per-phase EX/VT conformance

**PHASE-01** (EX-1..4, VT-1..6, VA-1) — model widen, protocol, pure projection.
All met. `protocol.py` deferred behind `detect` (off the `--help` path, EX-2);
`projection.apply` total+pure with inert unknown families (`test_apply_unknown_family_is_inert`
drives 7 malformed inputs); `_locate` renders label from the resolved entry only,
output from the id **prefix** when unresolved (`test_new_workspace_join_miss_is_incoherent_output_from_prefix`
asserts `workspace is None`, `output == "DP-9"`); EX-4/VA-1 layer-surface gate
discharged as accepted limitation in notes + schema.

**PHASE-02** (EX-1..4, VT-1..5) — session, coherence hold, equivalence. All met.
Snapshot-first (INV-U2) incl. empty-state snapshot; partial-burst discard; both
timeout paths; the coherence hold's three cases; equivalence VT-5
(`test_niri_sway_and_umbriel_cross_output_switch_land_equivalently`) is falsifiable
— asserts exact per-adapter event sequences (`niri` nulls→`window_focus`, `sway`
retains→`workspace_focus`, `umbriel` single-snapshot→direct `window_focus`),
connector-name outputs, matching distinct-workspace shape, and the `window_id`
type divergence (`102` int vs `"wb"` str).

**PHASE-03** (EX-1..4, VT-1/2, VA-1/2, VH-1) — live wire-up. EX-1..4 + VT-1/2 +
VA-1/2 met (detect three-way probe, `--compositor umbriel` choice, schema producer
entry, gate green). **VH-1 outstanding** (see below).

## Behaviour-preservation gate

**Holds.** No niri/sway/diff/histogram/runner/events source *or* test changed in
this diff. The two adjudicated exceptions are accounted for: (1) ISS-001's
`diff_state` promotion + 3 niri/equivalence test updates landed *before* this diff
(prior commits `c0ab29a`/`365e4f3`); (2) DL-6 is the only in-diff shared-model
change (`model.py:32`), a type-only widen — SL-002/SL-003 suites stay green
unchanged. The equivalence suite was *extended* with the umbriel arm (additive),
not altered in its niri/sway expectations. `test_compositor_detect.py`'s autouse
fixture was widened to clear umbriel's derivation vars so leaked host env can't
auto-probe umbriel — a correct preservation of the pre-umbriel suite's isolation.

## VT honesty

Every VT was checked to fail on regression, not pass vacuously:
- Timeout VTs drive a **real** silent-but-open socket (`_frames_then_hang`,
  `release`-gated handlers), not a mocked clock.
- VT-3 (attribution) replays the **real** `capture-1` fixture through the **real**
  `derive_segments` and pins the exact app sequence — the ISS-001 regression lock.
- VT-5 (equivalence) asserts exact, *divergent* per-adapter sequences — it would
  break if any adapter's emission shape drifted.
- Coherence VTs pin the resolved label value (`"mail"`) and assert nothing
  incoherent leaked, not merely a count.

## Outstanding (non-gating)

- **VH-1 — live-host acceptance.** `panopticon-desktop --compositor auto` on the
  live umbriel host writing `current/desktop.json` with a real focused window.
  Requires host access (umbriel is unreachable from the build jail). **Does not
  block close** (plan marks it VH, non-gating). David's to run when on the host.
- **RV-005.3 upgrade path.** If host access opens, a live layer-surface capture
  would downgrade the accepted limitation to "covered" or a precise bound
  (`notes.md` records the exact capture recipe).

## Findings (cosmetic, non-blocking)

1. **`detect.py` docstring cross-ref imprecision.** The module docstring (`:8`)
   and `_auto_select` (`:52`) cite **DL-4** for the niri-preference/probe order;
   in SL-005's design DL-4 is the *focus-model* decision and **DL-8** is the probe
   order + derived-socket eligibility. The niri>sway preference predates umbriel
   (SL-002/003), so the ref is a cross-slice ambiguity, not a code defect. Trivial
   doc tidy; safe to leave or fix opportunistically.

No correctness, purity, or coupling findings. The pure/impure split is clean
(`projection.py` has no I/O; `protocol.py`/`session.py` hold all impurity); the
shared `diff_state` is reused, not re-implemented (no parallel implementation).

## Carried forward (backlog candidates, not SL-005)

- **RV-005.5b** — `run_watcher` emits `compositor_reconnected` + resets backoff
  before the session's lazy connect (shared runner+niri concern).
- **Sway transient micro-segment** on two-step cross-output switch (pre-existing,
  orthogonal to ISS-001).
- **niri parallels** — the burst-completion hang (RV-005.5a) and `pid:-1` sentinel
  (DL-9) likely apply to niri too; fixed umbriel-local here, noted for niri.
