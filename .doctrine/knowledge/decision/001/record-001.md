# DEC-001: Keep Sway a first-class compositor; retire only the sway storage-naming bridge

<!-- Knowledge record body — context, detail, links. The structured, queried
     fields live in the sister `record-NNN.toml`; this prose is free-form and is
     never structurally parsed (the storage rule). -->

**Decision (owner, 2026-07-20, SL-004 design).** Panopticon keeps its "supports
Niri **and** Sway" claim. Sway remains a first-class compositor: the Sway adapter,
`--compositor sway`, and the `panopticon-sway` entrypoint/systemd unit all stay.
What SL-004 retires is only the *storage-naming bridge* left over from the
pre-migration `sway`-named world.

**The carve — five sway surfaces:**

1. Sway adapter / `--compositor sway` — **KEEP** (feature).
2. `panopticon-sway` entrypoint + systemd unit — **KEEP** (stable Sway alias).
3. `current/sway.json` side-write — **RETIRE** (SPEC-001 D2), after SATAN repoint.
4. `("sway","focus")` `_SOURCES`/retention entry — **RETIRE** (SPEC-001 OQ-4).
5. Historical `raw/sway-*.jsonl` — frozen; age out of the 7-day window.

**Why it's safe to keep 1–2 while dropping 3–4:** running Sway *today* goes through
the migrated neutral watcher, which writes `source:"desktop"` / `raw/desktop-*.jsonl`
/ `current/desktop.json` — never the `sway`-named files again. Sway support is
therefore orthogonal to the `sway` storage bridge.

**Load-bearing for future agents:** do **not** "just delete `panopticon-sway`" or the
Sway adapter as part of any cleanup — that removes a supported compositor, not dead
code. Only surfaces 3–4 are retirable.

Governs SL-004. Descends SPEC-001 D1/D2/D7 and OQ-2/OQ-4.
