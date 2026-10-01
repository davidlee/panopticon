# Design SL-008: digest: privacy-surface flag for gate audit

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

The deterministic gate (SL-006) decides what reaches the model, and nothing
tells us when it lets a private page through. SL-006 VH-1 sent the user's
own draft on a social site's compose page, found only by reading the records
by hand. The model already reads every page that is sent, so it can say when
a page looks private. A local audit can turn that into proposed `deny`
entries.

## 2. Current State

- `prompt.py`: strict `json_schema` reply `{summary, claims, entities}`;
  `EntityType(StrEnum)` is the single source for the entity enum, parser
  and type (SL-007). `parse_digest` is total; any shape mismatch is
  `bad_shape`. `PROMPT_VERSION = "3"`.
- `__main__.py`: `run()` loads the config, then dry-runs or digests.
  `_record` writes `url`, `host`, `title`, provenance and `asdict(digest)`
  to `digest/<sha[:2]>/<sha>.digest.json` via `StageStore`. `--dry-run`
  prints titles to stdout with whitespace collapsed only.
- `gate.gate(url, quality, length, cfg)` is pure; `length=None` defers
  `too_short`; `quality < cfg.min_quality` rejects.
  `normalise_deny_entry` rejects a path holding `?`, `#` or whitespace.
- 3 version-3 records exist. No backfill yet.

## 3. Forces & Constraints

- **Advisory only.** The flag is detection after egress. It never gates
  (SL-006: a model never decides whether text may reach a model).
- **Flag narrowly.** Public user-generated content (forum threads, public
  profiles) must not be flagged, or the audit drowns.
- **Missing flag ≠ evidence.** Small models miss things; a page can
  suppress its own flag by injection. The model never sees the URL path
  (SL-006 I1), and extracted text often loses editor chrome, so some
  surfaces may be undetectable. Low stakes: the cost is a missed proposal.
- **Local audit.** Reads stored records and the config: no network, no
  writes.
- **Untrusted text on a terminal.** Records hold model output and
  page-controlled titles and paths.
- Strict-mode `null` support varies by provider; an enum of strings does not.
- **No private data in the repo** (user, 2026-10-02). Which hosts or pages
  are private is itself private: deny entries live only in the user's
  `digest.toml`; audit output goes to stdout only; slice docs, notes,
  audits and tests carry aggregates and `*.example` hosts, never real
  hosts, URLs, titles or SHAs.

## 4. Guiding Principles

- One source of truth: a `PrivateSurface(StrEnum)` drives the schema enum,
  the prompt text, the parser and the type, as `EntityType` does.
- Reuse the gate and the deny-entry normaliser; don't reimplement matching.
- `StageStore` owns the record layout.

## 5. Proposed Design

### 5.1 System Model

```
 page ──▶ model ──▶ digest record {…, private_surface}
                                   │
 panopticon-digest --audit ◀───────┘  StageStore.records()
        │  keep: private_surface ∉ {public}
        │  keep: gate(url, current cfg) still Pass
        │  candidate = normalise_deny_entry(host/seg) that really denies url
        ▼
 stdout (sanitised): flagged rows + TOML-ready deny entries
```

### 5.2 Interfaces & Contracts

**Vocabulary** (`PrivateSurface`; meanings stated in the prompt):

| value             | meaning                                                                    |
|-------------------|----------------------------------------------------------------------------|
| `public`          | not private: includes public posts, threads, profiles and comments         |
| `draft`           | the signed-in user's own unpublished content: a compose, edit or draft view |
| `private_message` | a private conversation: email, direct message, private chat                |
| `account`         | the signed-in user's account surface: settings, security, admin            |
| `personal_record` | records about the signed-in user: orders, billing, finances, health, documents |
| `other_private`   | clearly private or pre-publication, but none of the above                  |

- Prompt: one bullet listing the values and meanings, plus "if unsure,
  `public`". "Use only what the page states" is scoped to summary, claims
  and entities.
- Schema: `private_surface: {"type": "string", "enum": [<values>]}`,
  required, **last** in `properties` and `required`, so the summary is
  generated first.
- `Digest.private_surface: PrivateSurface`; `_digest`'s key-set checks
  include it; an off-list value or missing key is `bad_shape` (D3).
- `PROMPT_VERSION = "4"`. The record carries the string value via `asdict`
  (as `EntityType` does).

**Store** — `StageStore.records() -> Iterator[tuple[str, dict | None]]`:
every record file (dotfiles excluded, as `done`), `None` when unreadable or
not a JSON object.

**Audit** — `panopticon-digest --audit [--root] [--config]`:
- `main` dispatches to `audit(root, config_path) -> int`, separate from
  `run()` (no env, transport or clock). Config loading is extracted from
  `run()` into one helper shared by both, keeping exit codes: missing → 0,
  malformed → 2. Ignores `enabled` and the API key.
- `--audit` with `--dry-run` or `--limit` is a usage error (`p.error`);
  `--dry-run --limit` stays legal.
- For each record:
  - `None`, or `private_surface` present but off-list → `malformed`.
  - `prompt_version` < 4 → `unflagged`. Version ≥ 4 without the field →
    `malformed`.
  - `public` → counted, not listed.
  - Otherwise, re-gated with `gate(url, cfg.gate.min_quality, None,
    cfg.gate)`: quality and length are not privacy rules, and passing the
    configured minimum neutralises quality under any config. `Reject` →
    `covered`; `Pass` → listed.
- Candidate per listed record: from the normalised path's first segment,
  `normalise_deny_entry(host_without_www + "/" + seg)`, or the bare host for
  a root path. It is kept only if the gate, with the candidate added to
  `deny`, rejects the URL as `denied_domain`; otherwise it falls back to the
  host. Query-addressed surfaces cannot be narrowed (D6).
- Output, every field through one `_printable` helper (non-printables,
  tabs and newlines escaped), shared with `--dry-run`:
  - per listed record: `reason<TAB>host<TAB>path<TAB>sha<TAB>title`;
  - per candidate: `deny<TAB>"<entry>"<TAB><distinct URLs>`;
  - last line: counts — each reason, `public`, `covered`, `unflagged`,
    `malformed`.
- Exit 0.

### 5.3 Data, State & Ownership

No new state. Records gain one field. The audit owns nothing.

### 5.4 Lifecycle, Operations & Dynamics

- Migration (as SL-007): delete the 3 version-3 records; the next run
  re-digests them on prompt v4. Then the backfill.
- The audit runs by hand, and after each backfill chunk. It is never wired
  into a unit file (I5).

### 5.5 Invariants, Assumptions & Edge Cases

- **I1:** every version-4 record has a `private_surface` in the
  vocabulary.
- **I2 (SL-006):** only `digest/client.py` imports a network module; the
  audit adds no network path.
- **I3:** the audit writes nothing.
- **I4:** nothing committed names a real private host, URL, title or SHA
  (§3). VH evidence is recorded as counts by reason. Hosts already public
  in `DEFAULT_DENY` are not private data.
- **I5:** audit output (paths, titles) goes to an interactive stdout
  only; `--audit` never runs under systemd, so it never reaches the
  journal (SL-006 I5: logs carry SHAs, statuses and kinds only).
- **I6:** every printed candidate parses as a deny entry and denies its
  URL.

## 6. Open Questions & Unknowns

None. OQ-1 (a `private_workspace` reason) → no (user, 2026-10-02).

## 7. Decisions, Rationale & Alternatives

- **D1: in the digest schema, now** (user, 2026-10-02). Pre-backfill, a
  schema change costs a re-digest of 3 records. Rejected: stage-2 triage
  (IDE-004's placement; it does not exist and needs a new provider);
  deferring (the backfill would then lack the flag).
- **D2: closed string enum; `public` is the negative, `other_private` the
  catch-all.** `public` is unambiguous where `none` read as both "public"
  and "no listed reason"; `other_private` follows `EntityType.OTHER`.
  Rejected: a bool (no reason, too coarse to act on); a nullable enum
  (uneven strict-mode `null` support); `private_workspace` (user: no).
- **D3: off-list value or missing key → `bad_shape`**, as SL-007 D3. The
  page gets a permanent fail marker and counts toward the content breaker;
  strict mode makes this rare (R4).
- **D4: the audit is a mode of `panopticon-digest`, as its own function.**
  It shares config loading and the store root. Rejected: a separate binary
  (duplicates setup); a flag inside `run()` (a growing mode switch).
- **D5: "still exposed" is decided by the real `gate`**, so a proposal
  disappears once a deny entry covers it.
- **D6: candidates are `host/<first segment>`, verified.** A whole host is
  often too wide (VH-1's case was one path on a public site). `www.` is
  stripped since hosts match by suffix. Query-addressed surfaces fall back
  to path or host; the user narrows or widens by hand.

## 8. Risks & Mitigations

- **R1: over-flagging public UGC.** Mitigation: `public` is named in the
  prompt, with "if unsure, public"; VH checks the canary chunk.
- **R2: under-flagging** (small model, missing URL path, injection).
  Accepted: advisory, no worse than today. VH measures it with synthetic
  positives.
- **R3: the flag biases the summary.** Low: the field is generated last.
  VH compares v3 and v4 output on the 3 records.
- **R4: an off-list value costs a page's digest for good** (D3). Accepted:
  strict schemas make it rare; the breaker bounds a bad model.
- **R5: a pasted candidate breaks the config** (a `ConfigError` turns off
  every run). Mitigation: I6.

## 9. Quality Engineering & Validation

- Schema enum equals the `PrivateSurface` values, last in the schema; the
  prompt names each and the "if unsure" rule.
- `parse_digest`: each value parses; off-list or missing → `bad_shape`.
- `PROMPT_VERSION == "4"`; the written record holds the bare string.
- `StageStore.records()`: dotfiles skipped; unreadable → `None`.
- Audit (tmp store, `*.example` hosts):
  - flagged and exposed → listed, with a candidate;
  - `public` → counted only; flagged but now denied, or not in `allow` →
    `covered`;
  - version-3 → `unflagged`; malformed, off-list, or version-4 without the
    field → `malformed`;
  - `min_quality > 1` still lists;
  - every candidate parses via the config parser and denies its URL;
    percent-encoded `?`/space segments fall back to the host;
  - an ANSI or OSC escape in a title or path is escaped (also `--dry-run`);
  - writes nothing; a raising transport is never called;
  - `--audit` with `--dry-run` or `--limit` is a usage error.
- VH (counts only, I4):
  - re-digest the 3 records: flags and summaries are plausible;
  - synthetic `*.example` positives (compose view, inbox, settings page,
    order history) through the real model: hits by reason;
  - a canary chunk: flagged count, spot-checked for public UGC.

## 10. Review Notes

Adversarial review (2026-10-02, a second agent; codex MCP unavailable):
15 findings, all adopted. Main changes: quality neutralised with the
configured minimum, not 1.0 (a `min_quality > 1` hid every record);
candidates verified through `normalise_deny_entry` and the gate (I6);
terminal sanitising, also fixing `--dry-run`; `none` → `public` plus
`other_private`; synthetic-positive VH for recall; `audit` separate from
`run()`; `StageStore.records()`; coverage counts; `www.` stripping and
distinct-URL counts; I5 stated; field last in the schema.
