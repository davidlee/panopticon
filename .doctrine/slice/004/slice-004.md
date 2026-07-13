# Desktop watcher docs and operational migration

## Context

Realises SPEC-001 (`references --role implements`); `needs SL-002`, `after SL-003`.
The evergreen-docs, operational, and compat-retirement tail — separated from the two
implementation slices because it lands last and touches out-of-repo state (systemd/HM
units, SATAN). Thin by design; may partly fold into the SL-002/SL-003 close-outs if
that proves cleaner at plan time.

## Scope & Objectives

Provisional (finalise at `/plan`):

1. **Docs.** `README.md` arch diagram/table, `docs/schema.md` (source, event list —
   currently stale), `docs/privacy.md` heading (policy text preserved verbatim).
   Sway↔Niri switching notes.
2. **Operational migration.** systemd `sway-watcher.service` + the out-of-repo HM unit
   `flakes/modules/home/linux/behaviour.nix` (OQ-2 — decide unit-name rename;
   ExecStart is `lib.getExe`, rename-safe). Migration-day historical-data handling
   (OQ-4): keep `sway` `_SOURCES`/retention entries on a raw-retention-dated
   retirement; migration-day equivalence test.
3. **Compat retirement.** Drop the `current/sway.json` side-write (D2) once SATAN is
   repointed to `current/desktop.json` across the four OQ-1 reader sites
   (`satan-tools-activity.el:111`, `satan-memory-evidence.el:662`,
   `satan-sensor-alerts.el:120`, `dl-sleipnir-doctor.el:266`) — a cross-repo change,
   coordinated but tracked here.

## Non-Goals

- Any watcher/adapter/schema logic (SL-002, SL-003).
- Editing SATAN internals beyond the `current/*.json` path repoint.

## Summary

Docs refresh + unit migration + retirement of the OQ-1 compat surface — the
close-out tail once both adapters exist.

## Follow-Ups

- If the SATAN repoint slips, the `current/sway.json` side-write stays; retirement
  becomes its own backlog item rather than blocking this slice's close.
</content>
