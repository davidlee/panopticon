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

## PHASE-02 — SATAN + doctor repoint (completed, external)

Read-only pre-survey of `/workspace/satan` + `/workspace/.emacs.d` (2026-07-20) →
worklist, scope carve, and OQ resolutions. Durable facts: OQ-1 answered (broad ERT
fixture surface beyond the plan's 4 production readers — `satan-memory-evidence-test.el`
alone ~8 sites); OQ-2 no-op (activity tool forwards the histogram to the LLM verbatim,
no key enumerated); OQ-3 dissolved (an agent running in-repo already has write access).
**Scope tripwire:** `satan-tools-sway.el` (`sway_border_set`/`swaymsg` live tools)
+ sway event-schema tests are Sway-as-a-feature — OUT of scope (DEC-001); touch a
`sway` match iff it is the `current/sway.json` storage path. Fence: keep the
`systemctl … panopticon-sway` remediation string (design D4).

**Execution handback (design R6 — external evidence; no in-repo delta).** Every reader
of the transitional `current/sway.json` side-write now points at the wm-agnostic
`current/desktop.json` primary (identical bytes; zero-downtime, content-identical).

| Repo | Ref | Message |
|---|---|---|
| `/workspace/satan` | `70687ec` | fix(SL-004): repoint SATAN current-window readers to current/desktop.json |
| `/workspace/.emacs.d` | `8a7533b` | fix(SL-004): repoint sleipnir-doctor current probe to current/desktop.json |

Sites repointed (production + fixtures): `satan-tools-activity.el` (activity_read
"current"), `satan-memory-evidence.el` (current-window probe + 2 docstrings),
`satan-sensor-alerts.el` (malformed-remediation `head -1` hint),
`.emacs.d/lisp/dl-sleipnir-doctor.el` (current probe); fixtures
`satan-memory-evidence-test.el` (file renamed + `sway-path`→`desktop-path` locals),
`satan-tools-activity-test.el`, `satan-resonance-test.el`, `satan-percept-test.el`.

- **EX-1 / VA-1 ✓** — `grep -rn --include='*.el' 'sway\.json\|current/sway'` returns
  zero readers in both repos (re-verified in-repo 2026-07-20).
- **EX-2 ✓** — retained `systemctl --user status panopticon-sway` remediation string
  UNCHANGED (unit name kept, design D4); persists in `satan-sensor-alerts.el` +3.
- **EX-3 (OQ-2) ✓** — no-op confirmed: `satan-tools-activity.el` forwards `:histogram`
  verbatim; no Elisp keys into `per_workspace_seconds`, so the niri `output/workspace`
  key passes through untouched.
- **EX-4 ✓** — committed in each external repo, scoped SL-004; refs captured above.
- **ERT ✓** — every touched suite green. One unrelated failure
  (`satan-db/test-db-available-p-probes-test-host`) is a Postgres-connectivity probe
  (DB host unreachable in the sandbox), not the repoint. Lint clean.

**Gate NOT crossed (design §5.5 INV — coordinator/human call):** the PHASE-03
side-write drop was NOT triggered. Repoint-before-drop and the sway-side-write
retirement remain deferred.

### VH-1 — SATISFIED on host (2026-07-20)

The design premise "`desktop.json` is already the primary write" held **in-repo**
but NOT on the host: the box was still running the pre-SL-002/003 sway-era watcher.
Host redeployed to `panopticon-desktop` 0.2.1 (`home-manager switch`), and
`current/desktop.json` is now live:

```json
{"window_id":296,"app_id":"com.mitchellh.ghostty","pid":3461334,
 "title":"…","workspace":"doctrine","output":"DP-3"}   // producer:"niri"
```

- `raw/desktop-2026-07-20.jsonl` fresh, live `source:"desktop"` / `producer:"niri"`
  events appending each second; `raw/sway-*.jsonl` frozen 19:32 (correct — nothing
  writes it now). `current/sway.json` side-write refreshed 159 B (was an 84 B/Jul-11
  corpse — current-window resolution had in fact been dead on the host for 9 days).
- The four repointed readers consume exactly this file (EX-1/VA-1 code-verified).
  Optional belt-and-suspenders eyeball if wanted: the Elisp doctor's `SATAN/sensors`
  line → `current=ok`, and `activity_read "current"` → the focused window.

**Deploy footgun (durable — cost us the whole detour).** `home-manager switch`
flips the unit *symlink* to the new store path, but `systemctl --user restart`
alone relaunches the **stale in-memory ExecStart** (the old `panopticon-sway`
binary → a sway watcher crash-looping on a niri host, still writing `raw/sway`).
`NeedDaemonReload=no` is a **false negative**: Nix store fragments carry a fixed
1970 mtime + are immutable, so systemd's mtime check never sees the retarget —
`systemctl cat` reads disk (new), the manager runs memory (old). **Fix: always
`systemctl --user daemon-reload` before `restart` after a HM switch.**

### Finding (out of scope) — `sleipnir-doctor-panopticon` is sway-keyed

`flakes:modules/home/linux/bin/sleipnir-doctor-panopticon` keys `SOURCES` (l23) on
`sway`/`firefox` with no `desktop` entry (+ `sway_fresh` gate l89/92/104-105,
`check_sway_journal` l156). Now that the desktop watcher runs, once `raw/sway` ages
past its 30-min threshold it false-WARNs "sway: no events today" and never tracks
the real producer. **Out of PHASE-04 scope** (behaviour.nix comments/smoke only;
this is a different file + a *functional* SOURCES change, which VA-1's
"only comments changed" would reject). A design-scope gap: §2 surveyed
`behaviour.nix` but not its sibling doctor script. Filed by the flakes agent in
`~/flakes/TODO.md`; retain the `journalctl --user-unit=panopticon-sway.service`
target (D4 alias). **For `/audit` disposition** — candidate appended PHASE-05 (same
"operational migration" intent) or a follow-up flakes slice.

## PHASE-04 — flakes ops refresh (completed, external)

Reframed the HM unit `flakes:modules/home/linux/behaviour.nix` for the
compositor-neutral desktop watcher (design R6 — external evidence, no in-repo delta).

| Repo | Ref | Message |
|---|---|---|
| `~/flakes` | `971282ef` | doc(SL-004): reframe panopticon HM unit for compositor-neutral desktop watcher |

5-line framing-only diff: header storage note → `raw/desktop-*.jsonl` +
`current/desktop.json`; smoke path `raw/sway-` → `raw/desktop-`; Description
de-Sway-framed ("desktop behaviour event watcher, compositor-neutral: sway|niri");
+2-line defensive comment pinning the retained `panopticon-sway` alias (D4).

- **EX-1 ✓ / VA-1 ✓** — comments + smoke reference the desktop reality; agent
  confirmed only behaviour.nix framing changed.
- **EX-2 ✓** — unit name `panopticon-sway` retained, `ExecStart ${lib.getExe
  panopticon}` unchanged, `panopticon-segmentize`/`panopticon-git` units untouched.
- **EX-3 ✓** — committed in flakes, scoped SL-004; ref captured above.
- **VH-1 — behaviour.nix evaluates cleanly** (build reached home-manager-path
  realization, past module eval; the edit is comment/string text only). The full
  switch is **red on a PRE-EXISTING, unrelated `television` collision** — NOT
  SL-004: `programs.television` (`modules/home/shared/nushell.nix:63`, wrapped `tv`)
  and a bare `pkgs.television` (`modules/shared/cli/_packages/find.nix:5`) both land
  `bin/tv` in the profile. A flakes-side defect, tracked in flakes, out of this
  slice.
