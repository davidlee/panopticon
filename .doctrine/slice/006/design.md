# Design SL-006: panopticon-digest: opt-in page digest over the content store

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

Captured pages have no summary. Add an opt-in batch job, `panopticon-digest`. It
sends gated page text to one remote model and stores a structured digest per
content SHA. It must not weaken the invariant that **capture never touches the
network** (DEC-002).

This slice delivers **gate + digest** (D1). Triage (jev) and embedding (Voyage)
are follow-up slices. This design only makes room for them (§5.3).

## 2. Current State

```
firefox ext ──native msg──▶ firefox_host ──▶ ContentStore.store()
                                              content/articles.jsonl        (index)
                                              content/<sha[:2]>/<sha>.json  (raw: text_content, length, …)
                                              content/<sha[:2]>/<sha>.md    (frontmatter + markdown)
```

- **Index rows** hold `content_hash, url, domain, title, extractor, captured_at,
  quality_score`. `length` and the body are only in `<sha>.json`.
- **First-sighting time.** The index `captured_at` is the **first** time a SHA was
  seen. On a duplicate, `ContentStore.store` rewrites `.json`/`.md` with the new
  `captured_at` but skips the index. The index is authoritative here.
- **Domain derivation.** `domain` is the lowercased hostname of the redacted URL.
  With no hostname, `firefox_host` stores `"unknown"`. `file://` pages reach the
  store when the host runs with `--record-file-urls`.
- **URL redaction.** It covers only the page's own URL. Links inside the body
  (the `.md` `href`/`src`) keep their full query strings.
- **Page identity.** Since ISS-003 (resolved), URLs keep per-host identity params,
  so URL → latest SHA is a valid page identity.
- **`quality_score` is discrete:** 1.0 minus 0.3 per penalty. Penalties are a
  missing title, link-heavy content, mostly short lines, and short text.
- **Precedents.**
  - `panopticon-segmentize`: a single-shot batch with `--root`, `-v` and atomic
    writes.
  - `panopticon-git`: a non-blocking `flock` single-instance guard.
- **Duplication.** `_atomic_write_text` is copied in `ingest/content.py` and
  `segmentizer/__main__.py`. `RawStore._write_current_file` is a third variant.
  The flock sequence is inline in `git_poller/poller.py`.
- **Network code.** None in capture, except dead code:
  - `ingest/extractor.py` fetches URLs through trafilatura's `focused_crawler`.
  - It has no callers outside its own test.
  - Panopticon has no config file and no HTTP dependency.
- **Units.** systemd user units are wired by the user's home-manager config,
  outside this repo. The repo ships the unit files.

## 3. Forces & Constraints

- **Privacy first.** The gate is deterministic and local, and it runs before any
  byte leaves the host. A model never decides whether text may reach a model.
- **Off by default, twice.** Nothing in this repo enables the timer. The binary
  does nothing without a config file that says `enabled = true`.
- **One egress seam.** Exactly one module opens network connections.
- **Pure/imperative split** (project convention): no clock, network or disk in
  the pure layer.
- **No new dependencies** (D2): stdlib `urllib`, `tomllib` and `json` only.
- **Volume is tiny:** ~13 pages/day after the gate. The backfill (~2.4k pages)
  is the only bulk case.

## 4. Guiding Principles

- **Store only what cost egress.** Gate verdicts are recomputed on every run, so
  a config change takes effect without a migration.
- **Key everything by content SHA.** A page whose content is unchanged is never
  re-sent.
- **Text in, text out.** No agent, no harness, no provider SDK.
- **Fail closed.** An unparseable URL, an unknown key or a missing host is a
  rejection or an error, never a pass.
- **Room for triage and embedding** comes from a stage-parameterised store, not
  from further abstraction.

## 5. Proposed Design

### 5.1 System Model

```
                 ┌──────────────── panopticon-digest (one run) ──────────────────┐
config.toml ───▶ │ load_config ─▶ DigestConfig      (strict; fail on unknown key)│
env (API key) ─▶ │ take lock (digest.lock)                                       │
content index ─▶ │ latest_per_url(index) ─▶ drop digested ─▶ cheap gate          │
                 │   (pure)                                  (scheme, host, q)   │
<sha>.json ────▶ │ read survivors' text_content ─▶ length gate        (pure)     │
                 │ order newest-first, take ≤ limit           ─▶ [Candidate]     │
                 │ for each candidate:                                           │
                 │   build_request(page, cfg)                         (pure)     │
                 │   client.post_json(...)   ◀── the only egress (client.py)     │
                 │   parse_digest(response) ─▶ Digest | Failure       (pure)     │
                 │   StageStore("digest").put(record)                            │
                 │   abort the run on auth/quota failure or N consecutive fails  │
                 └───────────────────────────────────────────────────────────────┘
```

Package `panopticon/digest/`:

| module        | role                                                               | pure? |
|---------------|--------------------------------------------------------------------|-------|
| `config.py`   | `parse_config(dict) -> DigestConfig`; frozen dataclasses; strict  | yes   |
| `gate.py`     | `normalise_host`, `gate(url, length, quality, cfg) -> Verdict`    | yes   |
| `select.py`   | `latest_per_url`, `select(...) -> [Candidate]`                    | yes   |
| `prompt.py`   | `build_request(page, cfg) -> dict`; `parse_digest(resp)`          | yes   |
| `client.py`   | `post_json(url, headers, body)`: no redirects, bounded retry      | no    |
| `store.py`    | `StageStore(root, stage)`: per-SHA records + per-stage index      | no    |
| `__main__.py` | CLI shell: wires the above, lock, logging, circuit breaker        | no    |

Shared, per D6:
- **New `panopticon/settings.py`:** `config_dir()` and `load_toml(name)`,
  mirroring `store.state_dir()`. The name avoids a clash with `digest/config.py`.
- **New `panopticon/fsutil.py`:** `atomic_write_text` and `exclusive_lock`,
  extracted from the existing copies (§2).

### 5.2 Interfaces & Contracts

**CLI**

```
panopticon-digest [--root PATH] [--config PATH] [--limit N] [--dry-run] [-v|-vv]
```

- **No config, or `enabled = false`:** log one line and exit 0. No lock, no
  writes, no network (I3).
- **`--dry-run`:** print each row's gate verdict, plus url, title and input size
  for each candidate. No network, no writes, no lock, and no API key needed. Use
  it to tune the denylist.
- **`--limit N`:** overrides `max_pages_per_run`. The backfill is a manual run
  with a large limit.
- **Exit codes:**
  - Non-zero on a config error, a missing API key, or a run aborted by the
    circuit breaker (§5.4).
  - Any other per-page failure is logged; the page is retried on the next run.

**Config**: `$XDG_CONFIG_HOME/panopticon/digest.toml`

```toml
enabled = true
max_pages_per_run = 50

[gate]
mode = "deny"                  # "deny" | "allow"
domains = ["example.internal"] # added to the shipped defaults in deny mode
use_default_denylist = true
min_chars = 1500
min_quality = 0.7              # = at most one quality penalty (OQ-3)

[digest]
endpoint = "https://openrouter.ai/api/v1/chat/completions"
model = "…"                    # required; no default (the allowlist is the user's)
api_key_env = "OPENROUTER_API_KEY"
max_input_chars = 24000
max_output_tokens = 1500
use_env_proxy = false
```

- **Strict parsing.** An unknown key is an error, so a typo cannot silently drop
  the user's denylist.
  - `endpoint` must be `https`.
  - Any key-shaped field (`api_key`, `token`, …) is rejected. Keys come only from
    the environment variable named by `api_key_env`.
  - The unit supplies that variable with `EnvironmentFile=` (or
    `LoadCredential=`).
- **Warning:** deny mode with `use_default_denylist = false` and no `domains`
  passes everything; this logs a warning.

**Gate**: `Verdict = Pass | Reject(reason)`. The reasons form an enum so tests
and dry-run output are stable.

| reason          | rule                                                                   |
|-----------------|------------------------------------------------------------------------|
| `bad_url`       | URL does not parse                                                     |
| `bad_scheme`    | scheme is not `http`/`https` (rejects `file`, `ftp`)                   |
| `no_host`       | URL has no hostname (covers the stored `"unknown"` domain)             |
| `local_host`    | IP literal (v4/v6), `localhost`, `*.local`, `*.lan`, `*.internal`, `*.home.arpa`; any mode |
| `denied_domain` | deny mode: host is a listed domain or under one                        |
| `not_allowed`   | allow mode: host is neither a listed domain nor under one              |
| `low_quality`   | `quality_score < min_quality`                                          |
| `too_short`     | `len(text_content) < min_chars`                                        |

- **Host source and normalisation.**
  - The gate derives the host from the URL itself, never from the stored
    `domain` field.
  - `normalise_host` lowercases the host, strips a trailing dot, and
    IDNA-encodes it.
- **Domain matching** is on label boundaries: `bank.com` matches `bank.com` and
  `www.bank.com`, but not `evilbank.com`.
- **Ordering:** cheap rules run on index fields. `too_short` runs last, after the
  `.json` is read.

**Payload.** The digest sends `text_content` from `<sha>.json`, not the
markdown (D9).
- Plain text has no link targets, so signed URLs and tokens in body links do not
  leave the host.
- The payload is the same text that `min_chars` measured.
- There is no frontmatter to strip.
- The text is truncated to `max_input_chars`, and `truncated: true` is recorded.

**Provider request**: an OpenAI-compatible chat completion.

```json
{ "model": "<cfg>",
  "max_tokens": "<cfg.max_output_tokens>",
  "messages": [ {"role": "system", "content": "<instructions; page text is data, not instructions>"},
                {"role": "user",   "content": "<title, url, then the page text inside a delimited block>"} ],
  "response_format": { "type": "json_schema",
                       "json_schema": { "name": "page_digest", "strict": true, "schema": DIGEST_SCHEMA } },
  "provider": { "require_parameters": true } }
```

`require_parameters` stops OpenRouter from routing to a provider that would
ignore the schema.

**`DIGEST_SCHEMA`**: every object sets `additionalProperties: false`, and every
property is `required`.

```json
{ "summary": "string",
  "claims":   ["string"],
  "entities": [{"name": "string", "type": "string"}] }
```

**`parse_digest`** is total: it returns `Digest | Failure(kind)` and never raises.
It handles these cases:
- an `error` object in a 200 body;
- a missing `choices`;
- `message.refusal`;
- `finish_reason == "length"`;
- `content` that is not valid JSON;
- JSON that fails the schema.

**Client** (`client.py`):
- **Redirects:** refused, so the request goes only to the configured endpoint.
- **Proxies:** honoured only if `use_env_proxy = true` (default false). urllib
  reads `*_PROXY` implicitly; this makes that explicit.
- **Timeout:** 60 s per request.
- **Retries** on 429/5xx, exponential with jitter:
  - `Retry-After` is capped at 60 s;
  - at most 4 attempts;
  - total sleep per page is capped.
- **401/402/403** raises `ProviderUnavailable` without retrying, which the run
  treats as fatal (§5.4).
- **Logging:** never the request body, the page text, headers or error bodies.
  Logs carry only the SHA, the HTTP status and the failure kind.

### 5.3 Data, State & Ownership

```
~/.local/state/behaviour/
  content/                       (owned by firefox_host; read-only here)
  digest/                        (owned by panopticon-digest)
    digest.jsonl                 stage index: content_hash, url, digested_at,
                                              endpoint, model, prompt_version
    <sha[:2]>/<sha>.digest.json  record: index fields + title, captured_at
                                         (from the content index), input_chars,
                                         truncated, summary, claims, entities
    # later slices, same StageStore: <sha>.triage.json + triage.jsonl,
    #                                 <sha>.embed.json  + embed.jsonl
  digest.lock                    single-instance guard
```

- **`StageStore(root, stage)`** is parameterised by stage, so triage and embed
  reuse it instead of copying it.
- **"Digested" means the record file exists.**
  - The index is a convenience for consumers, appended after the record.
  - A crash between the two loses an index row, so each run first appends rows
    for any records missing from the index (`reconcile_index`).
- **Egress ledger.** Each record stores `endpoint`, `model` and
  `prompt_version`:
  - `endpoint` records which provider saw the text;
  - `model` and `prompt_version` make drift detectable.
  - Re-digesting after a mismatch is manual (delete the records), not automatic.
- **Untrusted content.** Digests are untrusted derived text, since page content
  can steer them. The README says so for consumers (SATAN).
- **Retention.** Digest records follow content records.
  - RSK-001 owns content retention and must cascade deletion to `digest/`.
  - This slice adds no deletion (D7).

### 5.4 Lifecycle, Operations & Dynamics

- **Units, shipped but not enabled.**
  - `systemd/digest.service`: oneshot, `ExecStart=panopticon-digest`,
    `EnvironmentFile=-%h/.config/panopticon/digest.env`,
    `TimeoutStartSec=30min`.
  - `systemd/digest.timer`: daily, `Persistent=true`.
- **One run:**
  1. Load the config; if disabled, stop.
  2. Take the lock; if it is held, stop.
  3. Reconcile the index.
  4. Select candidates.
  5. Send, parse and store each candidate.
  6. Log counts per verdict and outcome.
- **Selection (D5):**
  1. Take the latest SHA per URL over **all** index rows, by first-sighting
     `captured_at` parsed as an aware datetime (the strings carry offsets).
  2. If that SHA is already digested, or the gate rejects it, the URL is done
     for this run. Never fall back to an older SHA.
  3. Order the survivors newest first and take up to `limit`.
  - **Known quirk:** a page that changes A → B → A ranks B as latest, because
    the index records first sightings. Accepted.
- **Churn.** A listing page whose content changes on every capture is digested
  at most once per run, and so roughly once per day. Triage (deferred) is the
  real fix. If that rate bites first, add a per-URL cooldown (OQ-5).
- **Circuit breaker.** The run stops and exits non-zero on
  `ProviderUnavailable` (401/402/403), or after 3 consecutive page failures.

### 5.5 Invariants, Assumptions & Edge Cases

- **I1:** nothing is sent for a candidate whose gate verdict is not `Pass`.
- **I2:** only `panopticon/digest/client.py` imports a network-capable module:
  - `urllib.request`, `http.client`, `ssl`, `socket`;
  - `trafilatura.spider`, `trafilatura.downloads`, `courlan`.
- **I3:** without a config that has `enabled = true`, a run makes no network
  call and writes nothing, not even the lock file.
- **I4:** re-running is idempotent; an existing record is never re-sent.
- **I5:** no log line contains page text, a request body or a credential.
- **Edge cases:**
  - An index row whose `.json` is missing is skipped and logged.
  - An unparseable index line is skipped; `_read_index` already does this.
  - A failed page leaves no record and is retried next run, under the circuit
    breaker.

## 6. Open Questions & Unknowns

- **OQ-1: which OpenRouter model?** It must support strict `json_schema` with
  `require_parameters`. Settle with one live call during execution. The model is
  config, so this does not block the design.
- **OQ-2: `max_input_chars`.** 24k chars covers roughly p90 (27 KB). Confirm
  against the model's context window and cost.
- **OQ-3: `min_quality`.** The score is discrete, so 0.7 means "at most one
  penalty". Check with `--dry-run` on the real corpus whether 0.4 (two
  penalties) is better.
- **OQ-4: the shipped default denylist.** It should list generic categories
  only, none of the user's actual domains:
  - mail, banking, chat, AI chat apps;
  - office suites, calendars, search result pages.
  - Check its coverage with `--dry-run`.
- **OQ-5: path-based rules.** Should the gate deny search-result paths
  (`google.com/search`) or apply a per-URL cooldown for listing pages? The
  design is domain-only; add either one only if dry-run data asks for it.
- **OQ-6: delete `ingest/extractor.py`?** This needs the user's call. It is dead
  network code with no callers outside its own test. Deleting it makes I2 true
  for the whole package, rather than true with an exemption.

## 7. Decisions, Rationale & Alternatives

- **D1: gate + digest only.**
  - Why: triage needs the jev DPA read first, and embedding needs a model choice.
    Shipping gate + digest keeps the day-one egress surface to one provider.
  - Rejected: all four stages, which blocks on two external checks.
- **D2: stdlib `urllib`.**
  - Why: no new nix or Python dependency, and the jev SDK is likely not in
    nixpkgs. The redirect and proxy handling and the retry loop are small.
  - Rejected: httpx (one more dependency) and vendor SDKs (nix packaging risk,
    three clients).
- **D3: TOML config, secrets only from env.**
  - Why: `tomllib` is in the stdlib. Env vars keep keys out of a file that is
    easy to commit or share. The loader goes in `panopticon/settings.py` so
    IDE-003 can reuse it.
  - Rejected: key-file paths in the TOML, and flags only (awkward for lists).
- **D4: denylist mode with shipped defaults; local and non-http hosts always
  denied.**
  - Why: matches DEC-002. Allowlist mode is available by config.
  - Rejected: allowlist by default (nothing works until curated) and an empty
    default (unsafe on the first run).
- **D5: latest SHA per URL over all rows, no fallback, newest first, bounded per
  run.**
  - Why: cuts listing-page churn within a run without triage, and keeps cost and
    backfill pacing predictable.
  - Rejected: a fallback to older SHAs, which would digest stale versions.
- **D6: extract `atomic_write_text` and `exclusive_lock` into
  `panopticon/fsutil.py`.**
  - Why: a third copy would be a parallel implementation. All three existing
    variants migrate, including `RawStore._write_current_file`, which then calls
    the helper.
  - Behaviour-preserving: the existing suites are the proof.
- **D7: no digest retention in this slice.**
  - Why: content is never deleted today, so orphan records cannot occur. RSK-001
    owns deletion and must cascade it.
- **D8: gate verdicts are not stored.**
  - Why: they are cheap and deterministic, so recomputing them applies config
    changes retroactively.
- **D9: send `text_content`, not the markdown.**
  - Why: body links in the markdown carry unredacted query strings (tokens,
    signed URLs). Plain text also matches what `min_chars` measures and needs
    no frontmatter parsing.
  - Cost: the model loses headings and list structure. Acceptable for a
    summary.

## 8. Risks & Mitigations

- **R1: the denylist misses a sensitive domain, so its text leaves the host.**
  - Local and non-http hosts are hard-denied, and defaults ship.
  - `--dry-run` before enabling; allowlist mode for the cautious.
- **R2: a page that always fails is retried, and charged for, on every run.**
  - The cost is tiny, and the circuit breaker bounds a bad run.
  - Failures are logged by SHA. A failure record with an attempt count is
    deferred until needed.
- **R3: the provider stores or trains on the text.**
  - The user checks retention terms before adding a provider (DEC-002).
  - The endpoint and model are explicit config with no defaults, and every
    record names its endpoint.
- **R4: prompt or model drift.** `model` and `prompt_version` are stored per
  record, so drift is detectable.
- **R5: prompt injection from page content.**
  - The model has no tools, so the effect is confined to the digest text.
  - Page text is fenced as data in the prompt.
  - Digests are documented as untrusted for downstream agents (second-order
    injection).

## 9. Quality Engineering & Validation

- **Pure units (TDD):**
  - `parse_config`: valid; missing model; unknown key; key-shaped field;
    non-https endpoint; the empty-denylist warning.
  - `gate`: every reason in the table, plus:
    - the trailing dot and case;
    - an IDN host;
    - `evilbank.com` vs `bank.com`;
    - IPv4/IPv6 literals and `*.local` in allow mode;
    - `file://`;
    - a stored `"unknown"` domain.
  - `latest_per_url`/`select`: latest gated means no fallback; already digested;
    mixed tz offsets; the limit; the ordering.
  - `build_request`: truncation flag; schema shape; `require_parameters`;
    page text inside the delimiter.
  - `parse_digest`: success, and each `Failure` kind.
- **Store:** `StageStore` round trip in `tmp_path`, idempotence (I4), and
  `reconcile_index` after a simulated crash between record and index.
- **Run level:** `run()` with an injected fake transport:
  - no-config no-op, with no lock file (I3);
  - dry-run makes no calls and no writes;
  - a gated page never reaches the transport (I1);
  - a failed page leaves no record;
  - a 401 aborts the run;
  - three consecutive failures abort the run.
- **Client:** a local `http.server` fixture:
  - a redirect is refused;
  - 429 with `Retry-After` is capped and retried;
  - 401 raises `ProviderUnavailable`.
- **I5:** a `caplog` test across a failing and a succeeding run asserts that no
  page text and no key appear in the logs.
- **I2 tripwire:**
  - A test walks the AST of `panopticon/**.py`. It fails if any module other
    than `digest/client.py` imports a module on the I2 list.
  - It cannot see network calls made through permitted libraries such as
    `asyncio.open_connection`; it is a tripwire, not a proof.
  - It depends on OQ-6: delete `extractor.py`, or exempt it by name.
- **D6 behaviour gate:** the content, store, segmentizer and git-poller suites
  stay green with no changes.
- **VH (verified by a human):** one live run against OpenRouter on a handful of
  pages, then manual inspection of the records (OQ-1).
- **Docs:**
  - README: the binary table, config, how to enable it, and that digests are
    untrusted text.
  - `docs/privacy.md`: the egress statement required by DEC-002.

## 10. Review Notes

**Round 1** (2026-10-01, adversarial subagent; codex MCP unavailable). The 17
findings were verified against the code, and all were accepted:

- **Gate holes:**
  - `file://` and the `"unknown"` domain could pass → `bad_scheme`/`no_host`;
    the host now comes from the URL.
  - A trailing-dot host evaded the denylist → `normalise_host`, label-boundary
    matching, and a wider set of local hosts.
- **Payload:** unredacted body links → D9, `text_content`.
- **Length:** a file `stat` cannot give `length` → read `.json` for survivors.
- **Selection:**
  - The order was unspecified, with an implicit fallback to older SHAs → §5.4
    and D5.
  - Timestamps need tz-aware sorting.
  - First-sighting `captured_at` is authoritative.
- **Request:** the `response_format` shape was wrong → corrected, with
  `require_parameters` and the full set of `Failure` kinds.
- **Retry:** no circuit breaker; unbounded `Retry-After` → capped retries,
  a breaker, and `TimeoutStartSec`.
- **Config:** unknown keys now fail; https only; empty-denylist warning.
- **Client hygiene:** no redirects; explicit proxy handling; I5 (no
  page text or credentials in logs).
- **Dead network code:** `extractor.py` → OQ-6; I2 widened to `ssl` and
  trafilatura/courlan.
- **I3 vs the lock:** config is now loaded before the lock.
- **Index loss:** a crash between record and index lost rows → `reconcile_index`.
- **D5 claim** corrected to "once per run".
- **Prompt injection** → R5: page text fenced, digests marked untrusted.
- **`quality_score` is discrete** → OQ-3 restated; `min_quality` set to 0.7.
- **Egress ledger** (`endpoint` per record) and `StageStore`, a stage-
  parameterised store.
- **Naming:** `settings.py` instead of `config.py`, and the
  `_write_current_file` variant folded into D6.
