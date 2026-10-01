# Design SL-006: panopticon-digest: opt-in page digest over the content store

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

Captured pages have no summary. Add an opt-in batch job, `panopticon-digest`, that
sends gated page text to one remote model and stores a structured digest per
content SHA, without weakening the invariant that **capture never touches the
network** (DEC-002).

This slice delivers **gate + digest** (D1). Triage (jev) and embedding (Voyage)
are follow-up slices; this design only leaves room for them (§5.3).

## 2. Current State

```
firefox ext ──native msg──▶ firefox_host ──▶ ContentStore.store()
                                              content/articles.jsonl   (index)
                                              content/<sha[:2]>/<sha>.json  (raw + length)
                                              content/<sha[:2]>/<sha>.md    (frontmatter + markdown)
```

- Index rows: `content_hash, url, domain, title, extractor, captured_at,
  quality_score`. `length` and the body are only in `<sha>.json` / `<sha>.md`.
- `domain` = lowercased hostname of the redacted URL. URLs keep per-host identity
  params since ISS-003 (resolved), so URL → latest SHA is a valid page identity.
- Precedents: `panopticon-segmentize` (single-shot batch, `--root`, `-v`, atomic
  writes) and `panopticon-git` (non-blocking `flock` single-instance guard).
- Duplication already present: `_atomic_write_text` is copied in
  `ingest/content.py` and `segmentizer/__main__.py`; the flock dance lives
  inline in `git_poller/poller.py`.
- No config file, no network code, no HTTP dependency anywhere in panopticon.
- systemd user units are wired by the user's home-manager config (outside this
  repo); the repo ships unit files.

## 3. Forces & Constraints

- **Privacy first.** The gate is deterministic and local; it runs before any
  byte leaves the host. A model never decides whether text may reach a model.
- **Off by default, twice.** The timer is not enabled by anything in this repo,
  and the binary does nothing without a config file that says `enabled = true`.
- **One egress seam.** Exactly one module opens network connections.
- **Pure/imperative split** (project convention): no clock, network, or disk in
  the pure layer.
- **No new dependencies** (D2): stdlib `urllib`, `tomllib`, `json`.
- Volume is tiny (~13 pages/day after the gate); the backfill (~2.4k pages) is
  the only bulk case.

## 4. Guiding Principles

- Store only what cost egress. Gate verdicts are recomputed every run, so a
  config change takes effect without migration.
- Key everything by content SHA; unchanged pages are never re-sent.
- Text in, text out. No agent, no harness, no provider SDK.
- Leave room for triage and embedding through the file layout, not abstractions.

## 5. Proposed Design

### 5.1 System Model

```
                 ┌──────────────── panopticon-digest (one run) ────────────────┐
config.toml ───▶ │ load_config ─▶ DigestConfig                                  │
env (API key) ─▶ │                                                              │
content index ─▶ │ select(index, digested, cfg) ─▶ [Candidate]   (pure)         │
                 │   ├─ gate(candidate, length, cfg) ─▶ Verdict  (pure)         │
                 │   └─ latest SHA per URL, minus already digested, ≤ limit     │
                 │ for each candidate:                                          │
                 │   read <sha>.md ─▶ build_request(page, cfg)   (pure)         │
                 │   transport.post_json(...)  ◀── the only egress (client.py)  │
                 │   parse_digest(response) ─▶ Digest | error    (pure)         │
                 │   DigestStore.put(record)  ─▶ digest/…                       │
                 └──────────────────────────────────────────────────────────────┘
```

Package `panopticon/digest/`:

| module        | role                                                         | pure? |
|---------------|--------------------------------------------------------------|-------|
| `config.py`   | `parse_config(dict) -> DigestConfig`; frozen dataclasses     | yes   |
| `gate.py`     | `gate(url, domain, length, quality, cfg) -> Verdict`         | yes   |
| `select.py`   | `select(index_rows, lengths, digested, cfg) -> [Candidate]`  | yes   |
| `prompt.py`   | `build_request(page, cfg) -> dict`; `parse_digest(dict)`     | yes   |
| `client.py`   | `post_json(url, headers, body, timeout)` + 429/5xx retry     | no    |
| `store.py`    | `DigestStore` — per-SHA records + `digests.jsonl` index      | no    |
| `__main__.py` | CLI shell: wires the above, lock, logging                    | no    |

Shared (D6): `panopticon/config.py` gains `config_dir()` + `load_toml(name)`,
mirroring `store.state_dir()`. A new `panopticon/fsutil.py` holds
`atomic_write_text` and `exclusive_lock`, extracted from the three existing
copies.

### 5.2 Interfaces & Contracts

**CLI**

```
panopticon-digest [--root PATH] [--config PATH] [--limit N] [--dry-run] [-v|-vv]
```

- No config file, or `enabled = false` → log one line, exit 0, no network.
- `--dry-run` → print each candidate's gate verdict and what would be sent
  (url, title, input size); no network, no writes. This is the tool for tuning
  the denylist.
- `--limit` overrides `max_pages_per_run` (backfill is a manual run with a big
  limit).
- Exit non-zero only on config errors or a missing API key; per-page failures
  are logged and retried on the next run.

**Config** — `$XDG_CONFIG_HOME/panopticon/digest.toml`:

```toml
enabled = true
max_pages_per_run = 50

[gate]
mode = "deny"                 # "deny" | "allow"
domains = ["example.internal"]  # added to the shipped defaults in deny mode
use_default_denylist = true
min_chars = 1500
min_quality = 0.5             # interim usefulness filter until triage (OQ-3)

[digest]
endpoint = "https://openrouter.ai/api/v1/chat/completions"
model = "…"                   # required; no default (the allowlist is the user's)
api_key_env = "OPENROUTER_API_KEY"
max_input_chars = 24000
```

- Keys are read from the environment variable named by `api_key_env` only. The
  unit file supplies them via `EnvironmentFile=` (or `LoadCredential=`); the
  TOML never holds a key, and `parse_config` rejects a key-shaped field.
- Domain match: exact host, or any subdomain of a listed domain
  (`bank.com` matches `www.bank.com`). Literal IPs and `localhost` are always
  denied in both modes.

**Gate** — `Verdict = Pass | Reject(reason)`; reasons are an enum
(`denied_domain`, `not_allowed`, `local_host`, `too_short`, `low_quality`) so
dry-run output and tests are stable.

**Provider request** — OpenAI-compatible chat completion with
`response_format = {type: "json_schema", strict: true, schema: DIGEST_SCHEMA}`.
User content = title + url + markdown body (frontmatter stripped, truncated to
`max_input_chars`). `parse_digest` validates shape and returns an error rather
than raising on a malformed reply.

**Digest schema**

```json
{ "summary": "string",
  "claims":   ["string"],
  "entities": [{"name": "string", "type": "string"}] }
```

### 5.3 Data, State & Ownership

```
~/.local/state/behaviour/
  content/                       (owned by firefox_host; read-only here)
  digest/                        (owned by panopticon-digest)
    digests.jsonl                index: content_hash, url, domain, digested_at,
                                        model, prompt_version
    <sha[:2]>/<sha>.digest.json  record: index fields + title, captured_at,
                                        input_chars, truncated,
                                        summary, claims, entities
    # later slices, same shape:  <sha>.triage.json, <sha>.embed.json (+ indexes)
  digest.lock                    single-instance guard
```

- A SHA counts as digested iff its record file exists. The index is an
  append-only convenience for consumers, written after the record (same order
  as `ContentStore`).
- `prompt_version` (a constant in `prompt.py`) and `model` are stored so a
  prompt or model change is detectable. Re-digesting on mismatch is manual
  (delete records), not automatic.
- Retention: digest records follow content records. RSK-001 owns content
  retention; when it lands, it removes the matching `digest/` records too
  (D7). This slice adds no deletion.

### 5.4 Lifecycle, Operations & Dynamics

- `systemd/digest.service` (oneshot, `ExecStart=panopticon-digest`,
  `EnvironmentFile=-%h/.config/panopticon/digest.env`) and `systemd/digest.timer`
  (daily, `Persistent=true`). Shipped, not enabled.
- One run: take the lock (skip if held) → load config → read the index → stat
  candidate `.json` files for `length` → select → for each candidate, send,
  parse, store → log counts (`gated`, `already`, `sent`, `stored`, `failed`).
- Selection keeps only the latest SHA per URL among pending rows, so a listing
  page recaptured ten times in a day costs one digest, not ten (D5).
- Order: newest `captured_at` first, so the daily run handles fresh pages and
  the backfill drains over days under `max_pages_per_run`.
- Retry: `client.py` retries 429 and 5xx with exponential backoff, honouring
  `Retry-After`, up to a small bound; then the page fails for this run.

### 5.5 Invariants, Assumptions & Edge Cases

- **I1** Nothing is sent for a candidate whose gate verdict is not `Pass`.
- **I2** Only `panopticon/digest/client.py` imports a network module
  (`urllib.request`, `http.client`, `socket`). A test enforces this over the
  whole package (§9).
- **I3** Without a config that has `enabled = true`, a run makes no network
  call and writes nothing.
- **I4** Re-running is idempotent: existing records are never re-sent.
- Edge: index row whose `.json` is missing → skipped and logged.
- Edge: a malformed provider reply → logged, no record, retried next run (R2).
- Edge: an index line that fails to parse is skipped (`_read_index` already
  does this).

## 6. Open Questions & Unknowns

- **OQ-1** Which OpenRouter model to use, and does it honour strict
  `json_schema`? Settle it with one live call during execution. The model is
  config, so this does not block the design.
- **OQ-2** What should `max_input_chars` be? 24k chars covers p90 (27 KB)
  roughly. Confirm against the model's context window and cost.
- **OQ-3** Is `min_quality = 0.5` right as the interim usefulness filter until
  triage lands? Check it with `--dry-run` against the real corpus.
- **OQ-4** What goes in the shipped default denylist? It should hold generic
  categories only (mail, banking, chat, AI chat apps, office suites,
  calendars, search result pages, localhost), and none of the user's actual
  domains. Check coverage with `--dry-run`.
- **OQ-5** Should search-result pages be denied by path (e.g. `google.com/search`)
  as well as by domain? The design proposes domain-only to start.

## 7. Decisions, Rationale & Alternatives

- **D1 Gate + digest only.** Triage needs the jev DPA read first, and embedding
  needs a model choice. Shipping the gate and the digest first keeps the
  day-one egress surface to one provider. Rejected alternative: all four
  stages, which blocks on two external checks.
- **D2 stdlib `urllib`.** This adds no nix or Python dependency, and the jev SDK
  is likely not in nixpkgs. The retry loop is roughly 20 lines. Rejected
  alternatives: httpx (one more dependency) and vendor SDKs (nix packaging
  risk, three clients).
- **D3 TOML config, secrets only from env.** `tomllib` ships in the stdlib. Env
  vars keep keys out of a file that is easy to commit or share. The
  `config_dir()`/`load_toml()` loader is generic, so IDE-003 can reuse it.
  Rejected alternatives: key-file paths in the TOML, and flags only (awkward
  for lists).
- **D4 Denylist mode with shipped defaults; local hosts always denied.**
  This matches DEC-002. Allowlist mode is available by config. Rejected
  alternatives: allowlist by default (nothing works until curated) and an empty
  default (unsafe on first run).
- **D5 Latest SHA per URL, newest first, bounded per run.** This removes
  listing-page churn without triage and keeps cost and backfill pacing
  predictable.
- **D6 Extract `atomic_write_text` and `exclusive_lock` into `panopticon/fsutil.py`.**
  A third copy would be parallel implementation. Migrating the three existing
  sites is behaviour-preserving, and the existing suites are the proof.
- **D7 No digest retention in this slice.** Content is never deleted today, so
  orphans cannot occur. RSK-001 owns deletion and must cascade to `digest/`.
- **D8 Gate verdicts are not stored.** They are cheap and deterministic, so
  recomputing them lets config changes apply retroactively.

## 8. Risks & Mitigations

- **R1 The denylist misses a sensitive domain, so its text leaves the host.**
  Mitigations: local hosts are hard-denied; shipped defaults; `--dry-run` before
  enabling; allowlist mode for the cautious.
- **R2 A page that always fails gets retried, and charged for, on every run.**
  The cost is tiny at this volume. Mitigation: log failures with the SHA. If it
  bites, add a failure record with an attempt count; this is deferred.
- **R3 The provider stores or trains on the text.** The user checks retention
  terms before adding a provider (DEC-002). Mitigation: the provider endpoint
  and model are explicit config with no defaults.
- **R4 Prompt or model drift makes old digests inconsistent with new ones.**
  `model` and `prompt_version` are stored per record, so drift is detectable.

## 9. Quality Engineering & Validation

- Pure units (TDD): `parse_config` (valid, missing model, key-shaped field
  rejected), `gate` (each reject reason, subdomain match, IP and localhost
  hard-deny in allow mode), `select` (latest per URL, already-digested
  excluded, limit, ordering), `build_request` (truncation, frontmatter
  stripped), `parse_digest` (valid, malformed).
- Store: round trip in `tmp_path`, plus idempotence (I4).
- Run-level: `run()` with an injected fake transport. It covers the no-config
  no-op (I3), the dry-run making no calls and no writes, a gated page never
  reaching the transport (I1), and a failed page leaving no record.
- **I2 guard**: a test that walks the AST of `panopticon/**.py` and fails if any
  module other than `digest/client.py` imports `urllib.request`,
  `http.client`, `ssl`, or `socket`. Today this holds trivially (the compositor
  adapters use `asyncio` unix sockets and i3ipc), and the test locks it. It is a
  tripwire, not a proof: `asyncio.open_connection` could still reach TCP.
- Behaviour-preservation gate for D6: the content, segmentizer and git-poller
  suites stay green unchanged.
- VH (verified by human): one live run against OpenRouter on a handful of
  pages, then manual inspection of the records (OQ-1).
- Docs: README (binary table, config, enabling) and `docs/privacy.md` (the
  egress statement, per DEC-002).

## 10. Review Notes

_Pending adversarial review._
