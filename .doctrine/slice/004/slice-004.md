# Desktop watcher docs and operational migration

## Context

Realises SPEC-001 (`references --role implements`); `needs SL-002`, `after SL-003`.
The evergreen-docs, operational, and compat-retirement tail — it lands last and
touches out-of-repo state (systemd/HM units, SATAN). Design locked 2026-07-20
(`design.md`): a **full cross-repo landing** — one agent holds both ends of the hose,
performing the SATAN repoint and the in-repo retirement together (design D2). Stands
as its own slice, not folded into SL-002/003.

## Scope & Objectives

Locked by `design.md` (2026-07-20). Governing carve: **keep Sway a first-class
compositor; retire only the sway storage-naming bridge** (design D1 / DEC-001).

1. **Docs.** `README.md` arch diagram/table (Sway + Niri as peers), `docs/schema.md`
   (source→`desktop` + `producer`/`output`/`window_id`; reconcile the stale event
   list to `derive.py`; document the `output/workspace` histogram key — SL-003 Q2),
   `docs/privacy.md` (`## Sway watcher`→`## Desktop watcher`, policy text verbatim).
2. **Operational migration.** Refresh the out-of-repo HM unit
   `flakes:modules/home/linux/behaviour.nix` (Sway-framed comments/smoke). **OQ-2
   resolved: keep the `panopticon-sway` unit name** (stable Sway alias, design D4);
   the unit already runs `panopticon-desktop` via `lib.getExe`. **OQ-4 resolved
   (design D3, option A):** drop the legacy `sway` `_SOURCES`/retention entry, relying
   on the deploy precondition (no in-window `raw/sway-*.jsonl`; owner-confirmed) — the
   stranding hazard is structural (shared `focus` prefix), so a registry-pin test +
   runbook check replace the (impossible) "won't-strand" code test.
3. **Compat retirement.** Repoint SATAN to `current/desktop.json` across the four
   reader sites (`satan:satan-tools-activity.el:111`,
   `satan:satan-memory-evidence.el:662` +`:100`/`:132`, `satan:satan-sensor-alerts.el:120`,
   `.emacs.d:lisp/dl-sleipnir-doctor.el:266`), then drop the `current/sway.json`
   side-write + the `current_aliases` capability. **Ordering (correctness):** repoint
   → confirm → drop; host deploy rebuilds SATAN/emacs before the retired watcher.

## Non-Goals

- Any watcher/adapter/schema logic (SL-002, SL-003).
- Removing Sway *support* — the adapter, `--compositor sway`, and the
  `panopticon-sway` entrypoint/unit are **retained** (design D1 / DEC-001).
- Editing SATAN internals beyond the `current/*.json` path repoint (+ the histogram-key
  prompt/doc touch-up if SATAN carries one).

## Summary

Docs refresh + unit-comment refresh + retirement of the sway storage-naming bridge
(side-write + legacy `_SOURCES`/retention), coordinated across three external repos —
the close-out tail once both adapters exist, with Sway kept first-class.

## Follow-Ups

- Deploy precondition (host, human): confirm no `raw/sway-*.jsonl` inside the 7-day
  window before the retired watcher deploys (owner-confirmed satisfied 2026-07-19).
- Leftover `current/sway.json` after retirement is inert; a one-off manual `rm`, not
  automated.
- `nix run` host confirmation is tracked separately (backlog CHR-001).
</content>
