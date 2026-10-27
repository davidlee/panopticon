# Implementation Plan SL-010: content handoff: host replies with the captured page's path

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Reference forms: `lib:reference/glossary.md` § reference forms. -->

## Overview

Three phases: host first, extension second, then docs and the signed manual
check.

## Sequencing & Rationale

- **Host first.** It is the testable half and defines the wire contract. It
  is safe to ship alone: with no `trigger` from today's extension every
  request normalises to dwell and the host writes nothing, so the deployed
  0.2.3 extension is unaffected. The store guard (D9) lands here and helps
  dwell traffic immediately.
- **Extension second.** Built against a host that already replies. Only
  static checks are automatable (D8); the behaviour is reviewed by agent
  (VA) and checked by hand in PHASE-03.
- **Docs and VH last.** Signing needs the user (AMO API credentials) and a
  manual install; the docs describe what was actually built.

## Notes

- The extension's reconnect-backoff reset (design §2) stays out of scope.
