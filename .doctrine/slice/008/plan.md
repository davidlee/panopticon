# Implementation Plan SL-008: digest: privacy-surface flag for gate audit

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Three phases: the reply field (pure), the audit (read-only mode), then the
egress runs that verify both.

## Sequencing & Rationale

- PHASE-01 first: the audit reads the field, and its tests need records
  that carry it.
- PHASE-02 lands before any live run, so the first real flags can be
  audited at once.
- PHASE-03 is the only phase that sends data. `enabled` stays `false`
  until then, so no version-3 record can be written in between.

## Notes

- `_printable` also fixes `--dry-run`, which prints page titles raw today
  (design §10). Small and same-module, so it rides PHASE-02.
- The backfill is operational and follows the slice; it is not a phase.
