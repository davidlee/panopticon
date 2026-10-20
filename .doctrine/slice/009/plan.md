# Implementation Plan SL-009: digest: scheduled run through the LLM gateway

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Three phases: the code change (pure config plus the key read), the docs,
then deployment through `~/flakes` and the live checks.

## Sequencing & Rationale

- PHASE-01 first: nothing can point at the gateway until loopback http and
  the key file are accepted.
- PHASE-02 before deployment, so the pushed revision documents what it does.
- PHASE-03 is the only phase that sends data or touches another repo. The
  flakes input is `github:davidlee/panopticon`, so deployment needs a push
  first. VH-0 (a manual `--limit 3`) runs before the timer's first firing:
  the spike did not cover the strict `response_format` through LiteLLM.

## Notes

- `~/flakes` holds unrelated uncommitted changes, including `flake.lock`.
  The input update must be staged on its own, or agreed with the user.
- The backlog of ~175 pending pages is operational, not a phase.
