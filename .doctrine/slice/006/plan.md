# Implementation Plan SL-006: panopticon-digest: opt-in page digest over the content store

Prose companion to `plan.toml`. Narrative only — no queried data lives here
(the storage rule); the phase list, criteria, verification, and links are
authored in the TOML. Use this for the plan's rationale and sequencing.
<!-- Cite entities by padded id (SL-020, REQ-059); phases as PHASE-01,
     criteria as EN-1/EX-1/VT-1/VA-1/VH-1. See .doctrine/glossary.md § reference forms. -->

## Overview

Four phases, inside out:

```
PHASE-01 groundwork ──▶ PHASE-02 pure core ──▶ PHASE-03 impure shell ──▶ PHASE-04 docs + reality
 fsutil, settings        config, gate,          client, store, run,        README, privacy.md,
 rm extractor, mv amo    select, prompt         CLI, units                 dry-run, live VH
 I2 tripwire
```

## Sequencing & Rationale

- **The groundwork comes first, while no digest code exists.** The D6 extraction
  is the risky change to shared machinery. Landing it alone keeps the
  behaviour-preservation gate clean: if a suite goes red, the cause is the
  extraction and nothing else. The same goes for the two egress removals. The
  I2 tripwire then lands while it is trivially true, and guards every later
  phase.
- **The pure core comes before the shell.** Every privacy decision (gate,
  selection, and what goes into the request) is pure and testable without a
  network. PHASE-03 only wires it up. A reviewer can audit the privacy surface
  in one phase.
- **The shell is one phase.** Client, store and run are small and tested
  together through the fake-transport run tests. Splitting them would add
  phase overhead without adding a gate.
- **Reality comes last.** The dry-run against the live store settles thresholds
  that the design deliberately left to data (OQ-2/3/4/5). The live VH run needs
  the user's model choice, which the web-agent provider comparison feeds. Only
  PHASE-04 depends on that research. PHASE-01 to PHASE-03 can run now.

## Notes

- **`uv.lock` re-lock (PHASE-01):** `uv lock` needs network access to the
  package index. If the jail blocks it, the user re-locks on the host. The
  phase's other exit criteria do not depend on it.
- **`tools/` import path (D15):** a `tools/__init__.py` plus pytest
  `pythonpath = ["."]` keeps `tools.amo` importable from tests, and ruff
  already lints the whole tree. `tools/` is not in the wheel: hatch packages
  only `panopticon`.
- **Default denylist:** `DEFAULT_DENY` is settled in design OQ-4. PHASE-04's
  dry-run checks its coverage against the real corpus, and only aggregates are
  recorded.
