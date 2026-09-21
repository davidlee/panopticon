# ISS-001: diff_state precedence drops app on coalesced cross-workspace focus

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Found by the SL-005 (umbriel adapter) adversarial review (RV-005.1, gpt-5.6-sol),
verified end-to-end. **Prerequisite for SL-005** — the umbriel adapter cannot emit
correctly-attributed segments until this lands.

## Defect

`segmentizer/derive.py::_next_focus` (the `workspace_focus` branch, lines 87-98)
**retains the running `app_id`** and never reads the event's own `app_id`. Meanwhile
`compositor/niri/session.py::diff_state` gives `(workspace, output)` change precedence
over window-identity change — so a transition that changes *both* the workspace and the
focused window (i.e. a cross-workspace focus switch) is emitted as a single
`workspace_focus`, and the deriver keeps the **previous** app.

**Proof:** replaying the umbriel `capture-1` observation sequence
(`snapshot(ghostty)` → `workspace_focus(discord,ws2)` → `workspace_focus(emacs,ws1)` →
…) through the real `derive_segments` attributes **every** segment to
`com.mitchellh.ghostty`, though focus actually moved discord→emacs→discord→emacs.

## Why sway/niri mostly escape it

- **Sway** emits a `workspace_focus` *then* a corrective `window_focus` (two i3ipc
  events) — the `window_focus` restores the app. Deriver's retain-app on
  `workspace_focus` is correct *for sway's two-event pattern*.
- **Niri** decomposes a switch into `WorkspaceActivated` (→ `workspace_focus`, often
  landing on an empty intermediate → window=None) then `WorkspaceActiveWindowChanged`
  (→ `window_focus`). Latent: it **does** bite when switching to an already-populated
  workspace in one event (both fields change at once), but the common empty-intermediate
  path emits the corrective `window_focus`.
- **Umbriel** delivers a full snapshot per event, so a cross-workspace switch is a
  single event with both fields changed → **always** collapses to one `workspace_focus`
  → mis-attributes. No corrective follow-up exists.

## Sketch of the fix (tractable — ~3 LOC + 3 test updates)

Correct the **emission precedence** so window-identity changes are never masked by a
simultaneous location change:

```
window_changed = _identity(new.window) != _identity(prior.window)
loc_changed    = (new.workspace, new.output) != (prior.workspace, prior.output)
if window_changed: return DesktopObservation("window_focus", …)   # deriver rekeys app+ws fully
if loc_changed:    return DesktopObservation("workspace_focus", …) # same window, ws/output label only
return DesktopObservation("window_title", …)
```

The deriver's `window_focus`/`snapshot` branch already reads app+workspace+output from
the event, so `window_focus` on a combined change attributes correctly, and a
window→None transition closes the segment cleanly (empty-workspace / defocus).
Verified through `derive_segments`: discord→emacs→… attribute correctly; the
empty-workspace case closes then reopens.

**Placement (DRY):** promote `diff_state` (+ `_identity`, `_compact`) out of
`niri/session.py` into a shared compositor module so niri **and** umbriel use one
implementation — no parallel emission logic.

**Behaviour change (deliberate) + gate reconciliation.** This changes niri's emitted
names on full-field-change transitions (`workspace_focus` → `window_focus`), which
*improves* niri's attribution (removes a transient wrong-app micro-segment). Three
niri-owned tests encode the old precedence and must be updated to the corrected names:
- `tests/test_compositor_niri_session.py::test_diff_state_precedence_workspace_beats_window_and_title` (asserts the buggy precedence directly)
- `tests/test_compositor_niri_session.py::test_switch_to_empty_workspace_emits_one_workspace_focus_window_none`
- `tests/test_compositor_equivalence.py` (the `[snapshot, workspace_focus, window_focus]` sequence)

Other niri diff tests (workspace-only, output-only, window-only, title-only) stay
green unchanged.

## Acceptance

- `diff_state` emits `window_focus` whenever the focused-window identity changes,
  even under a simultaneous workspace/output change; shared by niri + umbriel.
- A `capture-1`-derived fixture → observations → `derive_segments` regression asserts
  correct per-workspace app attribution.
- Full suite green; the three updated niri/equivalence assertions reflect corrected
  (improved) behaviour, documented as a fix, not a regression.

## Links

- Blocks: SL-005 (`references`/`needs` — see the slice).
- Origin: SL-005 `design.md` §10 RV-005.1.
