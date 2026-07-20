# Notes SL-004: Desktop watcher docs and operational migration

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## PHASE-01 — Docs refresh (completed)

**Finding — the design's 5-event list was incomplete; code is the record.** The
emitted event set is **12**, verified against
`panopticon/compositor/{sway,niri}/session.py` + `runner.py`:
- Common (both adapters): `snapshot`, `window_focus`, `window_title`,
  `workspace_focus`.
- Lifecycle (runner reconnect loop, both): `compositor_disconnected`,
  `compositor_reconnected`.
- Sway adapter only (i3ipc passthrough; Niri emits none): `window_new`,
  `window_move`, `window_fullscreen_mode`, `window_urgent`, `window_close`,
  `workspace_urgent`.
The prompt/design §9 shorthand named only 5. Owner chose "list all, mark adapter
scope"; `docs/schema.md` now documents the full set under a sway-only subsection.
The list now lives in schema.md (the evergreen record), not just here.

**VA-1 (event-name parity) — PASS.** Documented event bullets in schema.md's
"## Desktop events" section == the 12 code-emitted names (leading-token diff empty).

**VA-2 (privacy byte-preservation) — PASS.** `docs/privacy.md` diff vs HEAD is
exactly: heading `## Sway watcher` → `## Desktop watcher` + a framing note, and the
segmentizer-join sentence "while Sway was focused" → "while the compositor was
focused". Every capture/redaction bullet is byte-identical. Pre-edit baseline
sha256 `cae34cfb…8495` (68 lines).

**Deferred (not PHASE-01):** version skew `pyproject.toml` 0.1.0 vs `flake.nix`
0.2.1 — code concern, left for the retirement pass / a follow-up (design §6). The
README "213 tests" count was de-numbered (suite is now 326) rather than pinned to a
moving number.

**DEC-001 honored:** docs keep Sway a first-class peer — `--compositor sway`, the
retained `panopticon-sway` unit alias, and the retired-*source* framing are all
distinct from removing Sway support.
