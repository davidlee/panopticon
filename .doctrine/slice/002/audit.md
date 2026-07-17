# Audit SL-002: Compositor-neutral core and Sway migration

Hand-authored close-out audit (no scaffold). Conformance of the implementation
against `design.md` + `plan.toml`, plus a self-review of the four-phase diff.
Structured findings live in the reconciliation ledger **RV-001**
(`doctrine review show RV-001`); this file is the durable prose companion.

**Gate at audit time:** `267 passed, 3 skipped`, `ruff` clean (`uv run --extra dev
pytest -q` / `ruff check .` — `just` unavailable in-jail, recipes run direct).

## Verification — phase exit criteria

### PHASE-01 (neutral core)
- EX-1 `compositor/model.py` — ✅ `WindowRef`, `DesktopState.to_dict()` flattens to
  exactly `{window_id,app_id,pid,title,workspace,output}`, `DesktopObservation{event,
  fields,state}`, `CompositorSession/CompositorClient` protocols. `FocusState` not
  carried alongside (only two docstring mentions; `grep` finds no type).
- EX-2 `compositor/runner.py` — ✅ `process_session(session,store,producer)` loops
  `observations()`, no `get_tree`, no state threading, `-> None` (F3); `run_watcher`
  owns reconnect/backoff, emits `compositor_reconnected`/`compositor_disconnected`
  via `encode`; `Backoff` relocated here.
- EX-3 `compositor/events.py` — ✅ `encode` is `make_event("desktop", obs.event,
  producer=…, **obs.fields)` — the **sole** `source`/`producer` injector (INV-2,
  grep-confirmed); per-event `fields` ride through verbatim (F8).
- EX-4 dead-code retirement — ✅ `IpcEvent` relocated to `compositor/sway/project.py`;
  `stream`/`Ipc{Disconnected,Reconnected}`/`StreamMessage` gone, no importer remains;
  `sway_watcher/` holds only an empty `__init__.py` + the thin `__main__.py` wrapper.
- VT-1..VT-5 — ✅ green (`test_compositor_{events,runner,model}.py`).

### PHASE-02 (Sway adapter + D5)
- EX-1 `compositor/sway/project.py` — ✅ `app_id_from_container`, `find_focused`,
  `ancestor_name_of_type`, `focus_state_from_tree`→`DesktopState`; tree-walk behaviour
  unchanged.
- EX-2 `compositor/sway/session.py` — ✅ first observation is `snapshot`; a
  `container->(workspace,output)` index seeded by `get_tree` and refreshed by
  `get_tree` on `_STRUCTURAL` = `window::new/close/move` + `workspace::focus/init/empty`
  (session.py:34-43); `window::focus` takes identity from the payload, location from
  the index. **`output` retention (F9) is honoured in the session** — `_window_title`
  (`:132`), `_passthrough` (`:155`), `_workspace_urgent` (`:204`) and the non-focus
  `_window_close` (`:148`) thread the prior `state` through, so `current/desktop.json`
  keeps workspace/output across events that don't carry them. (Retention is *in the
  projection*, not only downstream in the deriver — verified by direct read.)
- EX-3 **D5 fix** — ✅ `_window_focus` (session.py:115-125) derives `workspace,output
  = index.get(con_id, …)` from the *focused container*; prior `state` is not even a
  parameter — location is never copied from prior state. Proven by the dedicated
  before/after test carrying the pre-fix (buggy) expectation as a behaviour-change note.
- EX-4 `compositor/sway/_i3ipc.py` — ✅ relocated `I3ipcSwayClient`, the only real
  `i3ipc.aio` importer; `IpcEvent` import repointed to `project.py`.
- VT-1..VT-3 — ✅ green (`test_compositor_sway_{session,project}.py`).

### PHASE-03 (schema migration + segmentizer)
- EX-1 `store.py` — ✅ `RawStore(source, root, *, current_aliases=())`; a
  `source="desktop"` store with `current_aliases=("sway",)` atomically writes
  `current/desktop.json` **and** `current/sway.json` (identical payload), raw is
  `raw/desktop-*.jsonl` (falls out of the source param).
- EX-2 `segmentizer/__main__.py` — ✅ `_SOURCES` gains `("desktop","focus")` keeping
  `("sway","focus")`; `retention._SEGMENT_PREFIX_FOR_RAW` adds `"desktop":"focus"`;
  `derive` called with `source` per raw prefix (no longer the bare default).
- EX-3 `segmentizer/derive.py` — ✅ focus key `(producer, output, app_id, workspace)`
  (D8); segment bodies carry `producer`+`output`; `_next_focus` closes on **both**
  `sway_disconnected` and `compositor_disconnected` (F6).
- EX-4 `segmentizer/histogram.py` — ✅ unchanged; still buckets on bare
  `app_id`/`workspace` (R4 deferred, recorded in `notes.md`).
- VT-1..VT-3 — ✅ green (`test_store.py`, `test_segmentizer_{derive,main}.py`).

### PHASE-04 (CLI + detection)
- EX-1 `desktop_watcher/__main__.py` — ✅ `panopticon-desktop --compositor
  auto|sway|niri`; `--compositor niri` (and `auto` with no Sway) raise
  `NotImplementedError` embedding the "land in SL-003" message. Verified live:
  `--help` resolves, `--compositor niri` raises the seam.
- EX-2 `compositor/detect.py` — ✅ `select_client` returns `(sway_client, "sway")`;
  ⚠️ `auto` resolves via a **`SWAYSOCK` env probe**, not an IPC connect-attempt as
  DD10/EX-2 word it — intentional, in-code-documented stand-in, full probe deferred to
  SL-003 (**RV-001 F-1**, tolerated).
- EX-3 `sway_watcher/__main__.py` — ✅ thin wrapper delegating to the desktop `main`
  with `["--compositor","sway",…]`; pyproject exposes both console scripts.
- VT-1/VT-2 — ✅ green (`test_desktop_main.py`, `test_compositor_detect.py`).
- VA-1 — ✅ `flake.nix:41 meta.mainProgram = "panopticon-desktop"` committed at HEAD;
  pyproject exposes `panopticon-desktop` + the `panopticon-sway` wrapper.
- VH-1 — ⚠️ **verified by inspection, host confirmation outstanding.** No `nix` CLI in
  this jail; `nix run` unrunnable here. The mainProgram move is committed and the
  console entrypoint resolves (`uv run panopticon-desktop --help` works). A one-line
  `nix run` confirmation on a nix host closes VH-1 (**RV-001 F-2**, non-gating).

## Drift vs design
- **None material.** Every named surface (`compositor/{model,runner,events,detect}.py`,
  `sway/{project,session,_i3ipc}.py`, `desktop_watcher/__main__.py`) is present with
  the design's names and shapes. INV-1/INV-2/INV-3 all hold in code.
- **F-1 (detect auto):** the only wording-vs-implementation gap — `SWAYSOCK` presence
  as a connect **precondition** rather than a connect **attempt**. Within DD10's "seam,
  not a lie" scope; the honest stand-in is documented at `detect.py:44-50`.

## Self-review (diff)
- **Load-bearing risk was the neutral contract shape** (get it wrong → SL-003/SL-004
  inherit a Sway-shaped core). Mitigated: the pull→push inversion is real
  (`process_session` has no `get_tree`, the runner is compositor-blind), and the D5 fix
  is isolated behind its own before/after test so the large mechanical move stayed
  honest.
- **INV-2 single injector** — grep-confirmed: `source`/`producer` are stamped only in
  `events.py::encode`. Adapters emit neutral observations; no per-adapter `make_event`.
- **No parallel implementation** — `focus_state_from_tree`, `RawStore`, `Backoff`,
  `transform`'s pure-mapping shape all survived (relocated/renamed, not rewritten). The
  old sway modules were **deleted**, not left as duplicate sources.
- **Latent edge (by design):** `_window_focus` on an index miss emits `(None,None)`
  location. Faithful to D5 (location = the focused window's ancestry; a miss = genuinely
  unknown), not a retention regression — retention applies to events that *don't carry*
  location, which is handled (EX-2 above).

## Deferred / latent (carried — see `notes.md`)
- **R4** — D8 histogram de-conflation unmet until SL-003; `histogram.py` still buckets
  on bare `app_id`/`workspace`. Inert for Sway (globally-unique names); load-bearing
  with Niri's per-output unnamed workspaces. Widening + SATAN `per_workspace_seconds`
  coordination land in SL-003.
- **R3** — shared `focus` segment-prefix overwrite; not triggered (Sway dormant, DD11).
  Resolution (merge raws by prefix before deriving) recorded for whoever re-lives it.
- **PHASE-02 interim wrapper** — folded at PHASE-04; `panopticon-sway` now delegates to
  the desktop CLI with the `("sway",)` current-alias side-write.

## Review ledger (RV-001) — findings & dispositions
- **F-1 (minor) — auto-detect env probe vs connect-attempt.** Disposition: *tolerated —
  carried to SL-003*; verified. Non-gating.
- **F-2 (nit) — VH-1 `nix run` unverified in-jail.** Disposition: *verified by
  inspection — host confirmation outstanding*; verified. Non-gating.
- No blockers raised; ledger `done`. Close gate (D-C9b) unobstructed.

## Open / follow-up
- **VH-1 host checkpoint** — run `nix run` on a nix host to confirm `panopticon-desktop`
  launches (mainProgram move). One line; not a defect.
- **SL-003 inheritances** — replace the `SWAYSOCK` env probe with the connect-validated
  D7 both-set/liveness resolver (F-1); widen the histogram key + coordinate SATAN (R4);
  live desktop-attention data resumes here.
- **Uncommitted env edits** — `flake.lock`, the `flake.nix` `just`/`jailed-gemini`
  hunks, and `.envrc` remain unstaged as the owner left them; only the `mainProgram`
  hunk was committed into PHASE-04. Not part of SL-002.
