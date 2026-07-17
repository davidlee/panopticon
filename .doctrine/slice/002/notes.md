# Notes SL-002: Compositor-neutral core and Sway migration

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## Deferred / latent (carry forward)

- **R4 — histogram D8 de-conflation deferred to SL-003.** PHASE-03 widened the
  focus-segment key to `(producer, output, app_id, workspace)` (D8), but
  `segmentizer/histogram.py::aggregate` still buckets `per_app_seconds` on bare
  `app_id` and `per_workspace_seconds` on bare `workspace` — it does not read
  `producer`/`output`. So D8's anti-conflation is **not** met at the histogram
  tier. Inert for Sway (globally-unique workspace names); becomes load-bearing
  with Niri's per-output unnamed workspaces. The histogram-key widening + the
  SATAN `per_workspace_seconds` shape change land in SL-003 (SQ3/F4). Histogram
  left unchanged here on purpose.
- **R3 — shared `focus` segment prefix overwrite.** Both `desktop` and `sway`
  raws derive to `segments/focus-DAY.jsonl`; a same-day pair would overwrite
  (the later `_SOURCES` entry wins). Not triggered in practice — Sway is dormant
  (DD11), so no new `raw/sway-*.jsonl` collides with live `raw/desktop-*.jsonl`.
  If Sway ever runs again alongside desktop, merge raws by segment-prefix before
  deriving.
- **PHASE-02 interim wrapper.** `panopticon-sway` still defaults `--source sway`
  and does not yet request the DD7 `current/sway.json` side-write; the
  `panopticon-desktop` CLI (source=`desktop`, `current_aliases=("sway",)`) is
  PHASE-04. `RawStore(..., current_aliases=…)` capability landed in PHASE-03.
