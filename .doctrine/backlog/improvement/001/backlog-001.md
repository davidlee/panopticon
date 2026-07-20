# IMP-001: Repoint sleipnir-doctor-panopticon SOURCES sway->desktop

`flakes:modules/home/linux/bin/sleipnir-doctor-panopticon` is a host health script
whose `SOURCES` dict (l23) keys off `sway`/`firefox` with **no `desktop` entry**.
Now that the compositor-neutral `panopticon-desktop` watcher is live (writes
`raw/desktop-*.jsonl`), this script:

- **false-WARNs** `raw/sway freshness: no events today` once the frozen
  `raw/sway-*.jsonl` ages past its 30-min threshold, and
- **never checks the real producer** — `raw/desktop-*.jsonl` is invisible to it.

## Fix sites (three)

- `SOURCES` (l23) — repoint `"sway"` → `"desktop"` (prefix stays `focus`).
- `sway_fresh` gate (l89, l92, l104-105) — the cross-source staleness hint keyed on
  `sway`; re-key to `desktop`.
- `check_sway_journal` (l156) — **keep** the `journalctl --user-unit=panopticon-sway.service`
  target (the unit NAME is a deliberately retained stable alias, SL-004 design D4);
  only the label/framing may want a touch.

## Provenance / scope

Surfaced during **SL-004 PHASE-02 host VH-1 verification** (2026-07-20). It is a
genuine **design-scope gap**: SL-004 §2 "operational migration" surveyed
`behaviour.nix` but not its sibling doctor script in the same `bin/` dir. Explicitly
**out of PHASE-04 scope** (behaviour.nix comments/smoke only; this is a *functional*
change VA-1's "only comments changed" would reject).

Lives in the flakes repo — also logged flakes-side in `~/flakes/TODO.md`. Tracked
here for SL-004 `/audit` visibility: disposition is either an appended SL-004 phase
(same operational-migration intent) or a standalone flakes slice. See SL-004
`notes.md` PHASE-02 "Finding (out of scope)".
