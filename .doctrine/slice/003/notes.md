# Notes SL-003: Niri adapter

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## PHASE-02

- **Equivalence granularity (D-P02-1).** A *single* cross-output focus change is
  one `workspace_focus` in niri (focus rides `focused_workspace_id`) but sway can
  render it as one `window_focus` (location from the ancestry index). So VT-4's
  "equal event-name sequence" holds only for a transition both adapters decompose
  identically — the equivalence test drives the *two-step* "switch to ws 2 on DP-2,
  land on window B", emitted by both as `[snapshot, workspace_focus, window_focus]`.
- **F-P02-1 (for reconcile/audit).** VT-4's wording "equal event-name sequence"
  reads stronger than the adapters can honour for a *collapsed* single-step
  cross-output switch. Realised honestly via the two-step scenario; worth a VT-4
  wording note at reconcile so a future reader does not expect single-step equality.
  The equivalence test deliberately does not assert the intermediate
  `workspace_focus`'s window (niri None vs sway prior-window — a real divergence).
- **Niri fields shape.** Live observations carry the flattened `to_state().to_dict()`
  uniformly across the 3 live events (unlike sway's per-event fields, e.g.
  `old_title`). Acceptable: the encoder spreads fields verbatim, the deriver keys
  off `state`, and INV-N3 governs event *names*, not field sets.
- **DRY seam.** `event_variant()` (projection.py) is the one reader of niri's
  tagged-union shape — shared by `apply` and the session burst gate. Test wire
  builders live in `tests/niri_wire.py` (projection + session + equivalence suites).

## PHASE-03

- **D7 auto = two per-adapter connect probes (A-1, human 2026-07-19).** `detect.py`
  probes each *set* socket var with an adapter-appropriate connect: niri via
  `protocol.probe` (connect → `"EventStream"` → `{"Ok":"Handled"}` → close), sway via
  a real `i3ipc.aio.Connection(socket_path=...).connect()`. niri probed first, so
  both-connect → niri (DL-4, encoded by order not list position). `_sway_reachable`
  (the RV-001 F-1 `SWAYSOCK`-presence stand-in) is fully retired. Adapter imports
  stay deferred → `--help` loads neither i3ipc nor the niri stack (smoke-verified).
- **i3ipc has no public close — probe teardown reaches into privates (F-P03-1).**
  `connect()` opens `_cmd_socket` + `_sub_socket` and `add_reader(_sub_fd, …)`;
  `_close_i3ipc` removes the reader and closes both sockets, guarded so an internals
  change never breaks the probe (the one-shot `asyncio.run` loop teardown backstops).
  Sway-probe teardown is only exercised live (VH-1) + the guarded fallback.
- **R4 histogram key (EX-2).** `per_workspace_seconds` keys on `f"{output}/{ws}"`
  iff the segment carries a non-None `output` (niri always does), else the bare
  `workspace` (legacy sway omits `output` → byte-identical). `per_app`/`per_hour`
  untouched — SATAN-safe per design §5.4 (Elisp never keys into per_workspace).
- **F-P03-3 (VH-1, reconcile).** Live `--compositor auto` end-to-end on the niri host
  (real focused window in `current/desktop.json`; producer `niri` raws) is a manual
  host check — unrunnable in-jail (niri unreachable). Non-gating.

## Audit / close-out (RV-003, 2026-07-19)

- **Verdict: ships clean.** 326 pass / 3 host-skip, ruff clean, behaviour-preservation
  gate held. Five findings, all terminal; no blocker. Full synthesis + brief in
  `review/003/review-003.md`.
- **F-1 (fixed in-audit).** `boundaries.toml` source-delta registry had drifted:
  PHASE-02 recorded as a zero-width range at the pre-phase test commit `3d43c38`,
  and PHASE-03's range *started* at PHASE-02's real code commit `07c7c7e` — so
  `07c7c7e` (session.py + normalization + equivalence) was orphaned from both.
  Symptom: `slice conformance` called `session.py` "undelivered" and `verify-vt`
  called PHASE-02 VT-1..4 UNATTRIBUTABLE, *despite a green suite*. Fix:
  `slice record-delta SL-003 PHASE-02 --commit 07c7c7e` → `undelivered:0`, VTs
  attributable. **Lesson (mem):** a green suite does not imply a truthful
  conformance ledger — cross-check the delta registry at audit.
- **F-2 aligned** (VT-4 wording — see F-P02-1, no divergence).
  **F-3 tolerated** (i3ipc private teardown — guarded + memory-anchored).
  **F-4 tolerated** (VH-1 host end-to-end deferred, non-gating — see F-P03-3).
  **F-5 fixed** (histogram.py header docstring de-sway-ified).
