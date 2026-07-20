# Design SL-004: Desktop watcher docs and operational migration

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. Upstream spec decisions cited as SPEC-001 D2/D8, OQ-2/OQ-4. -->

## 1. Design Problem

The close-out tail of SPEC-001. SL-002 (neutral core + Sway) and SL-003 (Niri)
are `done`; the producer already emits `source:"desktop"` and the deployed unit
already runs `panopticon-desktop` via `lib.getExe` (`flake.nix` `meta.mainProgram`).
What remains is not implementation but **reconciliation of the surfaces around the
migrated producer**: evergreen docs still describe a Sway-only world; a transitional
`current/sway.json` compat side-write still runs to keep four out-of-repo SATAN /
doctor readers alive; and a legacy `sway` segmentizer/retention registration lingers
for historical raws. This slice refreshes the docs, repoints the readers, and retires
the storage-naming bridge — **without** dropping Sway as a supported compositor.

Distinguishing feature vs SL-002/003: this is a **cross-repo coordination** slice.
It writes into three external repos (satan, .emacs.d, flakes) as well as panopticon,
and its correctness is a *sequencing* property (repoint before drop), not an
algorithm.

## 2. Current State

Confirmed by survey (2026-07-20), all against the working trees:

- **Producer: already migrated.** `source:"desktop"`, `raw/desktop-*.jsonl`,
  `current/desktop.json`; `SCHEMA_VERSION = 1` (the D1 `source`/`producer`/`window_id`
  rename did **not** bump the version — schema.md documents the new fields under v1).
  `flake.nix:41` `meta.mainProgram = "panopticon-desktop"`; the `panopticon-sway`
  systemd unit executes `panopticon-desktop` (auto-detect) through `lib.getExe`.
- **Side-write: live.** `store.py::write_current` loops `for name in (self.source,
  *self.current_aliases)`; `desktop_watcher/__main__.py:26,67` sets
  `_CURRENT_ALIASES = ("sway",)`, so `current/sway.json` is written beside
  `current/desktop.json` on every state change.
- **Segmentizer/retention: dual.** `_SOURCES` (`segmentizer/__main__.py:40-43`) holds
  both `("desktop","focus")` and legacy `("sway","focus")`; `_SEGMENT_PREFIX_FOR_RAW`
  (`retention.py:27-29`) maps both to `focus`.
- **SATAN/doctor readers: none repointed.** All four still read `current/sway.json`:
  `satan:satan-tools-activity.el:111`, `satan:satan-memory-evidence.el:662`
  (+ `:100` defcustom, `:132` docstring), `satan:satan-sensor-alerts.el:120`
  (`head -1 …/current/sway.json`), `.emacs.d:lisp/dl-sleipnir-doctor.el:266`.
- **Docs: entirely Sway-framed.** `README.md`, `docs/schema.md`, `docs/privacy.md`
  carry no `desktop`/`niri`/`producer` content; schema.md's event list is stale
  (`sway_disconnected`/`sway_reconnected` where code emits `compositor_disconnected`;
  missing `window_title`).
- **Incidental drift found:** version skew (`flake.nix` 0.2.1 vs `pyproject.toml`
  0.1.0); README's "213 tests" (SL-003 closed at 326).

## 3. Forces & Constraints

- **Keep Sway a first-class compositor** (owner decision, §7 D1). Panopticon must
  retain the claim "supports Niri **and** Sway": the Sway adapter, `--compositor sway`,
  and the `panopticon-sway` entrypoint/unit all stay. Only the *storage-naming bridge*
  (the `sway`-named files/registries) is retired.
- **Zero-downtime repoint.** The side-write already writes `current/desktop.json` as
  primary, so readers can repoint to a file that already exists and is fresh — there
  is never a window where a reader reads a missing file, provided drop follows repoint.
- **Cross-repo write access.** Execution must write satan, .emacs.d, flakes. In-jail
  those are read-only binds at `/workspace/*`; execution needs either temporary `rw`
  binds or an un-jailed run (different absolute paths). Design references external
  targets by **repo-relative path**, never a hardcoded absolute (§4).
- **Behaviour-preservation gate.** The SL-002/003 Python suites stay green *unchanged*,
  except the tests that assert the side-write itself (legitimately inverted here).
- **Storage rule / pure-imperative split.** No new domain logic; the only code delta
  is removing a compat option from the impure store shell and trimming two registries.

## 4. Guiding Principles

- **Retire the bridge, not the road.** Distinguish *running Sway* (feature, kept)
  from the *`sway`-named storage bridge* (transitional, retired). Running Sway today
  writes `raw/desktop-*.jsonl` — keeping Sway support needs none of surfaces 3–5.
- **Sequence for correctness.** One agent holds both ends of the hose:
  repoint readers → confirm → drop the writer. The phase cut falls out of this:
  docs → SATAN repoint → in-repo retirement (last).
- **Path-portable external edits.** Every out-of-repo target is `repo:relative/path`;
  a "locate each repo root" step resolves absolutes at execution, so the slice runs
  under either access mechanism.
- **Honest verification.** Where a property can't be a code test (the structural
  stranding hazard, §5.4), say so and move the guarantee to a documented runbook
  precondition — don't fake a green test.

## 5. Proposed Design

### 5.1 System Model

Four workstreams over one migrated producer. Three are edits to *surfaces around*
the producer (docs, readers, ops); one is a small in-repo code retirement.

```
  panopticon (docs)          panopticon (code retirement, LAST)
   README / schema / privacy   store.py / desktop_watcher / segmentizer / retention
        │                            │
        │  (evergreen refresh)       │  drop side-write + sway registries
        ▼                            ▼
  satan + .emacs.d (repoint) ──────▶ current/desktop.json is the sole current file
   4 readers: sway.json → desktop.json
        │
        ▼
  flakes (ops)  unit NAME kept; comments/smoke refreshed; OQ-2 = "keep the name"
```

The **five sway surfaces** and their disposition (the load-bearing carve):

| # | Surface | Disposition |
|---|---------|-------------|
| 1 | Sway adapter / `--compositor sway` | **KEEP** — core dual-compositor feature |
| 2 | `panopticon-sway` entrypoint + systemd unit | **KEEP** — stable Sway alias |
| 3 | `current/sway.json` side-write | **RETIRE** after repoint (SPEC-001 D2) |
| 4 | `("sway","focus")` `_SOURCES`/retention entry | **RETIRE** (SPEC-001 OQ-4) |
| 5 | Historical `raw/sway-*.jsonl` | frozen; age out of the 7-day window |

### 5.2 Interfaces & Contracts

- **Store.** Remove the `current_aliases` parameter from `RawStore` and the
  `write_current` fan-out loop → `write_current` writes exactly `current/<source>.json`.
  Dead capability: `desktop_watcher` is its only caller. `desktop_watcher/__main__.py`
  becomes `RawStore("desktop", args.state_dir)`.
- **Segmentizer registry.** `_SOURCES` → `(("desktop","focus",derive_segments),
  ("firefox","browser",derive_browser_segments))`. `_SEGMENT_PREFIX_FOR_RAW` →
  `{"desktop":"focus","firefox":"browser"}`.
- **SATAN read contract.** The four readers switch the *filename* only
  (`sway.json`→`desktop.json`); payload shape is unchanged (SL-002 kept the current
  payload field-compatible aside from the harmless internal `window_id` rename that
  these verbatim-passthrough readers never key on). The `~/.local/state/behaviour/`
  path is unchanged.
- **Histogram/LLM contract (SL-003 Q2).** `per_workspace_seconds` keys are
  `"output/workspace"` (niri) / bare `workspace` (legacy). `activity_read` forwards
  the histogram to the LLM verbatim — **no Elisp keys into it** — so this is a docs +
  (if present) prompt concern, not a code change.

### 5.3 Data, State & Ownership

- **Sole current-state file** post-retirement: `current/desktop.json`, owned by the
  store write path. `current/sway.json` ceases to exist (stale copies are inert; a
  human may delete the leftover).
- **Raw namespace.** `raw/desktop-*.jsonl` is the only focus-source raw produced;
  `raw/sway-*.jsonl` is frozen historical and never re-created (Sway runs write
  `desktop`).
- **No schema change.** `SCHEMA_VERSION` stays 1.

### 5.4 Lifecycle, Operations & Dynamics

**In-repo → cross-repo ordering (correctness):**

1. **Docs** (panopticon) — safe any time; no runtime coupling.
2. **Repoint** (satan, .emacs.d) — readers move to `current/desktop.json`, which is
   *already written* today. Zero-downtime.
3. **Confirm** readers resolve `desktop.json` (ERT if present; else host check).
4. **Retire** (panopticon, LAST) — drop side-write + sway registries; `sway.json`
   stops being written.
5. **Ops** (flakes) — refresh comments/smoke; unit name kept.

**Host deploy ordering** (human step, not enforceable in-repo, → runbook):
rebuild **SATAN/emacs first** (readers on `desktop.json`; both files still exist) →
then rebuild the **panopticon watcher** (side-write gone). Reversing it strands old
SATAN without `sway.json`.

**The OQ-4 stranding hazard is structural (honest finding).** `desktop` and `sway`
raws share the `focus-DAY.jsonl` segment prefix. Once the `sway` `_SOURCES` entry is
dropped, `_source_from_raw_name("sway-…")` is unknown → the reaper's optimistic
fallback (`retention.py:106-110`) matches the same-day **desktop** `focus` segment and
reaps the un-derived sway raw. **No code test can assert "won't strand"** — with the
shared prefix the reaper genuinely would. Safety is therefore a **deploy precondition**:
no `raw/sway-*.jsonl` within the 7-day window at cutover (owner-confirmed satisfied,
2026-07-19; permanent, since Sway now writes `desktop` raws). Chosen approach (§7 D3
option A): rely on the precondition + a registry-pin test; do **not** harden the
fallback (guards an impossible future).

### 5.5 Invariants, Assumptions & Edge Cases

- **INV — repoint precedes drop.** No commit sequence or host deploy drops the
  side-write before all four readers are on `desktop.json`.
- **INV — Sway remains runnable.** `--compositor sway`, the adapter, and
  `panopticon-sway` survive the slice; a Sway run produces a valid `desktop` stream.
- **ASM — readers are verbatim-passthrough** (SPEC-001 review, re-confirmed 2026-07-20):
  the four sites consume `current/*.json` as an opaque object; only the filename is
  load-bearing.
- **ASM — no in-window sway raws** (owner-confirmed): the retirement strands nothing.
- **Edge — leftover `current/sway.json`** after retirement is inert; documented as a
  manual cleanup, not automated (avoids a delete path in the store shell).

## 6. Open Questions & Unknowns

- **OQ-1 — Elisp test surface (satan/.emacs.d).** Unknown whether ERT coverage keys
  on `current/sway.json`. Resolve at execution: grep each repo; update fixtures if
  present, else fall back to a host smoke check. Non-gating for design.
- **OQ-2 — SATAN activity system-prompt.** Whether SATAN carries an LLM prompt that
  should mention the `output/workspace` histogram key format (SL-003 Q2). Resolve at
  execution: update if present, no-op if not.
- **OQ-3 — write-access mechanism.** Temporary `rw` binds vs un-jailed run. Logistics,
  settled at `/plan` or execution; owner leans `rw` binds to preserve the single-session
  coordinated landing. Does not affect design content.
- **Incidental (fold or defer, owner call at plan):** version skew (`pyproject.toml`
  0.1.0 vs `flake.nix` 0.2.1) and README's stale test count. Cheap to align in the
  docs/retirement passes; not core to the slice's intent.

## 7. Decisions, Rationale & Alternatives

- **D1 — Keep Sway a first-class compositor; retire only the storage-naming bridge.**
  (Owner, 2026-07-20.) Surfaces 1–2 kept, 3–4 retired. *Rationale:* running Sway today
  writes `desktop` raws, so Sway support is orthogonal to the `sway`-named bridge; and
  the project wants to keep its dual-compositor claim. *Alternative rejected:* keep the
  `current/sway.json` side-write permanently as a fallback (belt-and-suspenders) —
  leaves a redundant write path and a second current-state file forever for no live
  consumer once SATAN reads `desktop.json`.
- **D2 — Full cross-repo landing in one slice.** (Owner, 2026-07-20.) SL-004 performs
  the SATAN repoint + flakes ops + in-repo retirement together — "one agent holds both
  ends of the hose." *Rationale:* the drop and the repoint must stay in lockstep;
  splitting risks a version where a reader reads a file that is written-not-yet or
  gone. *Alternative rejected:* in-repo docs now, defer retirement to a backlog item
  (the slice's own follow-up) — safe but leaves the bridge indefinitely and re-opens a
  coordination gap later.
- **D3 — OQ-4: rely on the deploy precondition, don't harden the reaper (option A).**
  (Owner, 2026-07-20.) Drop both sway registrations; pin the retired registry with a
  test; document the precondition. *Rationale:* the precondition is satisfied and
  structurally permanent (no future `sway-*` raws), so hardening the fallback (option B)
  guards an impossible case and broadens reaper semantics. *Alternative (B):* conservative
  fallback (unknown source → keep, never reap) — safe but accumulates unknown-source
  raws and complicates the reaper for a case that cannot recur.
- **D4 — OQ-2 (unit rename): keep the `panopticon-sway` unit name.** Follows D1 — the
  unit is a stable Sway alias. *Rationale:* renaming churns flakes + the
  `systemctl … panopticon-sway` remediation string for a cosmetic gain, and the unit
  already auto-detects the live compositor. *Alternative rejected:* rename to
  `panopticon-desktop` for honesty — defensible but contradicts "keep the alias."
- **D5 — Path-portable external references.** Targets recorded as `repo:relative/path`
  with a locate-root step. *Rationale:* execution may run jailed (`/workspace/*`) or
  un-jailed (real `$HOME`); absolutes would break one of them.

## 8. Risks & Mitigations

- **R1 — Cross-repo write access.** External repos are read-only in-jail. *Mitigation:*
  settle mechanism at execution (temporary `rw` binds or un-jailed); path-portable
  references (D5) keep the slice runnable either way.
- **R2 — Unknown Elisp test surface.** *Mitigation:* grep each external repo at
  execution; update fixtures if present, else host smoke check (OQ-1).
- **R3 — Deploy-ordering discipline.** SATAN must deploy before the retired watcher.
  Not enforceable in-repo. *Mitigation:* explicit runbook step in `notes.md` / commit
  messages; zero-downtime property (both files exist pre-drop) bounds the blast radius
  to the deploy instant.
- **R4 — Stranding of in-window sway raws.** Structural (shared `focus` prefix).
  *Mitigation:* deploy precondition (no in-window `raw/sway-*.jsonl`; owner-confirmed),
  registry-pin test, runbook check. (§5.4, D3.)
- **R5 — Docs drift back to stale.** schema.md event names must match code.
  *Mitigation:* reconcile the event list against `derive.py` / the session encoders at
  write time; consider a lightweight names-⊆-code check (nice-to-have, §9).

## 9. Quality Engineering & Validation

- **Python (panopticon).** Existing SL-002/003 suite stays green *unchanged* except:
  remove `test_store.py:59-78` (side-write aliases), invert `test_desktop_main.py:64`
  (assert `current_aliases == ()` / no `sway.json`), and drop the `source=="sway"`
  derive-equivalence assertions in the segmentizer suite. **Add** a registry-pin test:
  `_SOURCES` / `_SEGMENT_PREFIX_FOR_RAW` contain exactly `desktop` + `firefox` (no
  `sway`) — so a future re-add is deliberate. `just check` (ruff + tests + fmt) green.
- **Docs.** Reviewed for accuracy against code; event-name list reconciled to
  `derive.py` (`snapshot`, `window_focus`, `workspace_focus`, `window_title`,
  `compositor_disconnected`). Optional: a test asserting schema.md's documented event
  names ⊆ the code's emitted set.
- **SATAN / .emacs.d.** ERT if the path is covered (OQ-1); otherwise host verification —
  the doctor and `activity_read "current"` resolve the focused window from
  `current/desktop.json`.
- **flakes.** No unit-name change → no systemd validation churn; the existing
  `nix run` host confirmation is tracked separately (backlog CHR-001).
- **Cross-repo evidence.** Four commits, one per repo, scoped `SL-004`; the coordinated
  landing + deploy order captured in `notes.md` at close.

## 10. Review Notes

- Adversarial pass pending (design skill step 6). Attack surface to probe: (a) is the
  "zero-downtime repoint" claim airtight — any reader that caches the path or reads at
  a moment the primary write hasn't happened? (b) does dropping `current_aliases` from
  `store.py` disturb any *other* caller or test beyond the two identified? (c) is the
  registry-pin test the right shape, or does it lock in incidental structure? (d) the
  `sway_disconnected` legacy close-branch in `derive.py:99` — retire alongside (dead
  once no sway raws derive) or keep as harmless? Left as an optional cleanup pending
  the pass.
</content>
</invoke>
