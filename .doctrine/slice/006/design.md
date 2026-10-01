# Design SL-006: panopticon-digest: opt-in page digest over the content store

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

Captured pages have no summary. Add an opt-in batch job, `panopticon-digest`,
that sends gated page text to one remote model and stores a structured digest
per content SHA. It must not weaken the invariant that **capture never touches
the network** (DEC-002).

This slice delivers **gate + digest** (D1). Triage (jev) and embedding (Voyage)
are follow-up slices; this design only makes room for them (§5.3).

## 2. Current State

```
firefox ext ──native msg──▶ firefox_host ──▶ ContentStore.store()
                                              content/articles.jsonl        (index)
                                              content/<sha[:2]>/<sha>.json  (raw: text_content, length, …)
                                              content/<sha[:2]>/<sha>.md    (frontmatter + markdown)
```

- **Index rows** hold `content_hash, url, domain, title, extractor, captured_at,
  quality_score`. `length` and the body exist only in `<sha>.json`.
- **First sighting.** The index `captured_at` is the capture time the extension
  sent with the SHA's **first** sighting. On a duplicate, `ContentStore.store`
  rewrites `.json`/`.md` with the new `captured_at` but skips the index. The index
  is authoritative.
- **Domain.** `domain` is the lowercased hostname of the redacted URL; with no
  hostname, `firefox_host` stores `"unknown"`. `file://` pages reach the store
  when the host runs with `--record-file-urls`.
- **URL redaction** covers only the page's own URL: query and fragment are
  stripped, except identity params (ISS-003, resolved). It keeps the full netloc
  (including any `user:pass@`) and the full path. Links inside the body (the
  `.md` `href`/`src`) keep their full query strings.
- **`quality_score` is discrete:** 1.0 minus 0.3 per penalty. The penalties are a
  missing title, link-heavy content, mostly short lines, and short text.
- **Precedents.** `panopticon-segmentize` is a single-shot batch with `--root`,
  `-v` and atomic writes. `panopticon-git` uses a non-blocking `flock`
  single-instance guard, which `tests/test_git_poller.py` takes directly with
  `fcntl.flock`.
- **Duplication.** `_atomic_write_text` is copied in `ingest/content.py` and
  `segmentizer/__main__.py`; `RawStore._write_current_file` is a third variant.
  The flock sequence is inline in `git_poller/poller.py`.
- **Network code.** Capture has none, apart from dead code that D10 deletes:
  `ingest/extractor.py` fetches URLs through trafilatura's `focused_crawler`, has
  no callers outside its own test, and is trafilatura's only importer.
- **No config, no HTTP dependency.** Panopticon has no config file and no HTTP
  dependency. The README says "No network calls" (lines 11 and 119).
- **Units.** The systemd user units are wired by the user's home-manager config,
  outside this repo. The repo ships the unit files, and the flake builds every
  `[project.scripts]` entry.

## 3. Forces & Constraints

- **Privacy first.** The gate is deterministic and local, and runs before any
  byte leaves the host. A model never decides whether text may reach a model.
- **Off by default, twice.** Nothing in this repo enables the timer, and the
  binary sends nothing without a config file that says `enabled = true`.
- **One egress seam.** Exactly one module opens network connections.
- **Pure/imperative split** (project convention): the pure layer touches no
  clock, network or disk.
- **No new dependencies** (D2). Stdlib `urllib`, `ssl`, `tomllib` and `json`
  only; D10 removes one dependency (trafilatura).
- **Volume is tiny**: about 13 pages/day after the gate. The backfill
  (about 2.4k pages) is the only bulk case.

## 4. Guiding Principles

- **Store only what cost egress.** Gate verdicts are recomputed every run, so a
  config change applies without migration.
- **Key everything by content SHA.** Unchanged pages are never re-sent.
- **Text in, text out.** No agent, no harness, no provider SDK.
- **Fail closed.** An unparseable URL, an unknown config key, a missing host or
  an un-encodable host is a rejection or an error, never a pass.
- **Send the minimum.** Only the host, title and body text leave the machine;
  the URL path never does.
- **Write less code.** Add an index, an option or a record kind only when
  something needs it.

## 5. Proposed Design

### 5.1 System Model

```
                 ┌──────────────── panopticon-digest (one run) ───────────────────┐
digest.toml ───▶ │ load + parse config (strict)          ─ error → exit 2         │
                 │ not enabled and not --dry-run          ─ exit 0, touch nothing │
env API key ───▶ │ key missing (and not --dry-run)        ─ exit 2                │
                 │ take digest.lock (non-blocking)        ─ held → exit 0         │
content index ─▶ │ pending(index, done, cfg)  (pure) ─▶ ordered rows, cheap gate  │
                 │ walk rows newest-first, until `limit` candidates:              │
<sha>.json ────▶ │   read text_content ─▶ length gate                      (pure) │
                 │   build_request(page, cfg)                              (pure) │
                 │   client.post_json(...)   ◀── the only egress (client.py)      │
                 │   parse_digest(response) ─▶ Digest | Failure            (pure) │
                 │   store record (.digest.json) or failure (.digest.fail.json)   │
                 │   transport/provider failure → breaker                         │
                 └────────────────────────────────────────────────────────────────┘
```

Package `panopticon/digest/`:

| module        | role                                                                  | pure? |
|---------------|-----------------------------------------------------------------------|-------|
| `config.py`   | `parse_config(dict) -> DigestConfig`, frozen dataclasses, strict      | yes   |
| `gate.py`     | `DEFAULT_DENY`, `normalise_host`, `gate(...) -> Verdict`              | yes   |
| `select.py`   | `pending(rows, done, cfg) -> [Row]`, latest per URL, newest first     | yes   |
| `prompt.py`   | `PROMPT_VERSION`, `build_request(page, cfg)`, `parse_digest(resp)`    | yes   |
| `client.py`   | `post_json(url, headers, body)`: fixed opener, bounded retry          | no    |
| `store.py`    | `StageStore(root, stage)`: `done()`, `put()`, `put_failure()`         | no    |
| `__main__.py` | CLI shell: config, lock, walk, breaker, logging                       | no    |

Shared code (D6):
- **New `panopticon/settings.py`:** `config_dir()` and `load_toml(path)`,
  mirroring `store.state_dir()`.
- **New `panopticon/fsutil.py`:** `atomic_write_text(path, text)`, plus
  `@contextmanager exclusive_lock(path) -> Iterator[bool]`. The lock is a
  non-blocking `fcntl.flock(LOCK_EX | LOCK_NB)` on an `O_CREAT` file, and yields
  whether it was acquired. That is the poller's current behaviour, which
  `test_git_poller.py` relies on.

### 5.2 Interfaces & Contracts

**CLI**

```
panopticon-digest [--root PATH] [--config PATH] [--limit N] [--dry-run] [-v|-vv]
```

| situation                                         | behaviour                                   | exit |
|---------------------------------------------------|---------------------------------------------|------|
| no config file                                    | log one line, touch nothing                 | 0    |
| malformed config (also with `--dry-run`)          | log the error                               | 2    |
| `enabled = false`, no `--dry-run`                 | log one line, touch nothing                 | 0    |
| API key env var unset, no `--dry-run`             | log the variable name                       | 2    |
| lock held                                         | log and skip                                | 0    |
| run completes (per-page content failures allowed) | log counts                                  | 0    |
| breaker trips (§5.4)                              | log the cause                               | 1    |

- **`--dry-run`** needs a valid config but ignores `enabled` and the API key, so
  the user can dry-run before enabling. It prints every row's verdict, and the
  host, title and input size of each would-be candidate. It makes no network
  call, writes nothing and takes no lock.
- **`--limit N`** overrides `max_pages_per_run`. The backfill is a manual run
  with a large limit.

**Config**: `$XDG_CONFIG_HOME/panopticon/digest.toml`

```toml
enabled = true
max_pages_per_run = 50

[gate]
deny  = ["mybank.example"]   # always applied, on top of DEFAULT_DENY
# allow = ["lwn.net", …]     # optional; when present, only these hosts pass
min_chars = 1500
min_quality = 0.7            # = at most one quality penalty (OQ-3)

[digest]
endpoint = "https://openrouter.ai/api/v1/chat/completions"
model = "…"                  # required; no default (the allowlist is the user's)
api_key_env = "OPENROUTER_API_KEY"
max_input_chars = 24000
max_output_tokens = 1500
```

- **Strict parsing.** An unknown key at any level is an error, so a typo cannot
  silently drop the denylist; a literal `api_key` field is refused by the same
  rule. `endpoint` must be `https`, and `model` is required.
- **Domain normalisation.** Every `deny` and `allow` entry goes through
  `normalise_host`; an entry that does not normalise is a config error.
- **Secrets.** Keys come only from the env var named by `api_key_env`. The unit
  supplies it with `EnvironmentFile=`.
- **Allow narrows, never widens (D4).** `deny` (`DEFAULT_DENY` plus the user's
  entries) and the local-host rules always apply. `allow` can only remove hosts
  from what deny lets through. No setting turns a deny entry into a send.

**Gate**: `gate(url, title, quality, length | None, cfg) -> Pass | Reject(reason)`.
Reasons form an enum, so tests and dry-run output are stable. Rules are
evaluated in table order:

| reason          | rule                                                                      |
|-----------------|---------------------------------------------------------------------------|
| `bad_url`       | URL does not parse, or its host does not normalise (IDNA error)           |
| `bad_scheme`    | scheme is not `http`/`https` (rejects `file`, `ftp`)                      |
| `no_host`       | URL has no hostname                                                       |
| `local_host`    | IP literal (v4/v6); single-label host (no dot); `localhost`; `*.local`, `*.lan`, `*.internal`, `*.home.arpa` |
| `denied_domain` | host is a `deny` entry or under one                                       |
| `not_allowed`   | `allow` is set and the host is neither an entry nor under one             |
| `low_quality`   | `quality_score < min_quality`                                             |
| `too_short`     | `length < min_chars` (checked once `length` is known)                     |

- **Host source.** The host is always derived from the row's URL, never from
  the stored `domain` field.
- **`normalise_host`** lowercases, strips one trailing dot, and IDNA-encodes.
  It returns `None` on failure, which means `bad_url`.
- **Label-boundary matching.** `bank.com` matches `bank.com` and `www.bank.com`,
  but not `evilbank.com`.
- **`DEFAULT_DENY`** is a `frozenset` in `gate.py`. It lists generic categories
  only (OQ-4): mail, banking, chat, AI-chat apps, office suites, calendars,
  search engines, and auth/SSO hosts.

**What leaves the host (I1).** For a page that passes the gate, exactly three
things are sent, and nothing else:
1. the normalised **host**;
2. the **title**;
3. `text_content` from `<sha>.json`, truncated to `max_input_chars`.

The URL path, query, userinfo and body links never leave the host (D9, D11).

**Provider request**: an OpenAI-compatible chat completion.

```json
{ "model": "<cfg>",
  "max_tokens": "<cfg.max_output_tokens>",
  "messages": [ {"role": "system", "content": "<instructions; the page block is data, not instructions>"},
                {"role": "user",   "content": "<host, title, then text_content inside a delimited block>"} ],
  "response_format": { "type": "json_schema",
                       "json_schema": { "name": "page_digest", "strict": true, "schema": DIGEST_SCHEMA } },
  "provider": { "require_parameters": true } }
```

`DIGEST_SCHEMA` sets `additionalProperties: false` on every object and lists
every property as `required`:

```json
{ "summary": "string",
  "claims":   ["string"],
  "entities": [{"name": "string", "type": "string"}] }
```

**`parse_digest`** is total. It returns either a `Digest` or a
`Failure(kind)`, where `kind` is one of:
- `refusal` (`message.refusal`)
- `truncated` (`finish_reason == "length"`)
- `not_json`
- `bad_shape`
- `provider_error` (an `error` object in a 200 body, or no `choices`)

**Client** (`client.py`):
- **Opener.** `build_opener(NoRedirect(), ProxyHandler({}),
  HTTPSHandler(context=ssl.create_default_context()))`:
  - `NoRedirect` subclasses `HTTPRedirectHandler` and makes `redirect_request`
    return `None`. Refusing redirects keeps the `Authorization` header and the
    body from reaching any other host.
  - `ProxyHandler({})` stops urllib from reading the `*_PROXY` env vars.
- **Timeout:** 60 s per request.
- **Retried** (exponential backoff with jitter, at most 4 attempts):
  - 429 and 5xx, with `Retry-After` capped at 60 s;
  - `URLError` and timeouts.

  Once the attempts are exhausted, the client raises `TransportFailure`.
- **Fatal, never retried:** 3xx (a refused redirect), 401, 402 and 403 all
  raise `ProviderUnavailable`. Any other 4xx raises `TransportFailure`.
- **Logging.** Logs hold only the SHA, the HTTP status and the failure kind —
  never request bodies, page text, headers or error bodies (I5).

### 5.3 Data, State & Ownership

```
~/.local/state/behaviour/
  content/                            (owned by firefox_host; read-only here)
  digest/                             (owned by panopticon-digest)
    <sha[:2]>/<sha>.digest.json       record
    <sha[:2]>/<sha>.digest.fail.json  content-failure marker: kind, at, model, prompt_version
    # later slices, same StageStore:  <sha>.triage.json, <sha>.embed.json
  digest.lock                         single-instance guard
```

**Record fields:**

| field            | source                                                        |
|------------------|---------------------------------------------------------------|
| `content_hash`   | the content index                                             |
| `url`            | the content index (local only — it was never sent)            |
| `host`           | the normalised host that was sent                             |
| `title`          | the content index                                             |
| `captured_at`    | the content index (first sighting)                            |
| `digested_at`    | the run                                                       |
| `endpoint`       | config — the egress ledger: which provider saw the text       |
| `model`          | config                                                        |
| `prompt_version` | `PROMPT_VERSION` in `prompt.py`                               |
| `input_chars`    | length of the text sent                                       |
| `truncated`      | whether the text was cut to `max_input_chars`                 |
| `summary`        | the provider response                                         |
| `claims`         | the provider response                                         |
| `entities`       | the provider response                                         |

- **Done.** A SHA is *done* when either its record or its fail marker exists.
  `StageStore.done()` returns that set by globbing; there is no index (D12).
- **Retrying a failure.** To retry a content failure, delete its marker.
  Re-digesting after a model or prompt change is likewise manual: delete the
  records.
- **Untrusted text.** Digests are untrusted derived text, because page content
  can steer them. The README says so, for consumers such as SATAN.
- **Retention.** Digest files follow content records. RSK-001 owns content
  retention and must cascade to `digest/`. This slice deletes nothing (D7).

### 5.4 Lifecycle, Operations & Dynamics

**Units** (shipped, not enabled):
- `systemd/digest.service`: oneshot, `ExecStart=panopticon-digest`,
  `EnvironmentFile=-%h/.config/panopticon/digest.env`, `TimeoutStartSec=30min`.
- `systemd/digest.timer`: daily, `Persistent=true`.
- New `[project.scripts]` entry: `panopticon-digest`.

**One run** follows the sequence in §5.1.

**Selection (D5):**
1. `pending()` takes the latest row per URL over **all** index rows, by
   `captured_at` parsed as an aware datetime.
2. It drops rows that are done and rows the cheap gate rejects. It never falls
   back to an older SHA of the same URL.
3. It orders the remainder newest first.
4. The shell walks that list lazily. It reads `<sha>.json` only for the rows it
   reaches, applies `too_short`, and stops at `limit` candidates.

**Known quirks:**
- A page that goes A → B → A ranks B as latest, because the index records
  first sightings. Accepted.
- A listing page whose content changes every capture is digested at most once
  per run, so about daily. Triage, which is deferred, is the real fix; a
  per-URL cooldown is the fallback if it bites (OQ-5).

**Breaker:**
- A content failure (`refusal`, `truncated`, `not_json`, `bad_shape`) writes a
  fail marker and the run continues. Deterministic failures never block
  progress.
- `ProviderUnavailable` aborts the run at once.
- 3 consecutive `TransportFailure` or `provider_error` results abort the run.
- An aborted run exits 1 and leaves no marker for the page it aborted on.

### 5.5 Invariants, Assumptions & Edge Cases

- **I1:** Nothing is sent for a page whose verdict is not `Pass`. For a page
  that passes, only the host, title and truncated `text_content` are sent.
- **I2:** Only `panopticon/digest/client.py` imports `urllib.request`,
  `http.client`, `ssl` or `socket`.
- **I3:** Without `enabled = true`, a non-dry run makes no network call and
  writes nothing, not even the lock file. A dry run never makes a network call
  and never writes.
- **I4:** Re-running is idempotent: a done SHA is never re-sent.
- **I5:** No log line contains page text, a request body or a credential.

**Edge cases:**
- An index row whose `.json` is missing is skipped and logged.
- An unparseable index line is skipped (`_read_index` already does this).

## 6. Open Questions & Unknowns

- **OQ-1:** Which OpenRouter model? It must support strict `json_schema` under
  `require_parameters`. One live call during execution settles this; the model
  is config.
- **OQ-2:** `max_input_chars`. 24k chars covers roughly the p90 page (27 KB).
  Confirm against the model's context window and cost.
- **OQ-3:** `min_quality`. With `min_chars ≥ 500`, 0.7 means "at most one
  penalty" (no title, link-heavy, or short lines). Check 0.7 against 0.4 with
  `--dry-run` on the real corpus.
- **OQ-4:** The contents of `DEFAULT_DENY`: generic categories only, none of
  the user's own domains. **Settle in `/plan`** as a concrete list, then check
  its coverage with `--dry-run`.
- **OQ-5:** Path rules or a per-URL cooldown. The design is domain-only; add
  either only if dry-run data asks for it.

## 7. Decisions, Rationale & Alternatives

**D1: Gate + digest only.**
- Triage needs the jev DPA read; embedding needs a model choice. Shipping gate
  and digest first keeps day-one egress to one provider.
- Rejected: all four stages.

**D2: Stdlib `urllib`.**
- No new dependency, and the jev SDK is likely not in nixpkgs. The opener
  wiring is in §5.2.
- Rejected: httpx and the vendor SDKs.

**D3: TOML config; secrets only from the environment.**
- `tomllib` is in the stdlib, and env vars keep keys out of a file that is easy
  to share.
- The loader lives in `panopticon/settings.py` so IDE-003 can reuse it.
- Rejected: key-file paths, and config by CLI flags only.

**D4: Deny always applies; allow only narrows.**
- `DEFAULT_DENY` plus the user's `deny`, plus the local-host rules, apply on
  every run. An optional `allow` restricts further.
- This realises DEC-002's denylist with an optional allowlist, and no setting
  can flip a deny entry into a send.
- Rejected:
  - a single `mode` + `domains` list, which inverts its meaning when the mode
    changes;
  - allow-by-default;
  - an empty default.

**D5: Latest SHA per URL, with no fallback.**
- Newest first, lazy, bounded per run. This cuts listing-page churn within a
  run and keeps backfill pacing predictable.
- Rejected: falling back to an older SHA, which would digest stale versions.

**D6: Extract `atomic_write_text` and `exclusive_lock` into
`panopticon/fsutil.py`.**
- All three atomic-write variants and the poller's lock migrate.
- This is behaviour-preserving: the existing suites stay green unchanged.

**D7: No digest retention in this slice.** Content is never deleted today.
RSK-001 owns deletion and its cascade.

**D8: Gate verdicts are not stored.** They are cheap and deterministic, so a
config change applies retroactively.

**D9: Send `text_content`, not markdown.**
- Body links in the markdown carry unredacted query strings.
- Plain text matches what `min_chars` measures and needs no frontmatter
  parsing.
- Cost: the model loses headings and list structure.

**D10: Delete `ingest/extractor.py`, its test, and the trafilatura dependency.**
- Decided by the user on 2026-10-01.
- The file is dead network code; trafilatura is removed from `pyproject.toml`
  and from both `flake.nix` lists.
- I2 then holds over the whole package with no exemption.

**D11: Send the host, not the URL.**
- Stored paths can carry secrets: share links, token pages, OAuth flows. The
  netloc can carry userinfo.
- The host and title give the model enough context; the text carries the
  content.
- Rejected: the redacted URL with userinfo stripped, which still sends paths.

**D12: No digest index.**
- "Done" means a record or fail marker exists, and consumers glob the records.
  This removes the index-loss window and the reconcile code.
- An index can be added when a consumer needs one.

**D13: Content failures are recorded; only transport and provider failures
trip the breaker.**
- A deterministic failure would otherwise abort every run at the same place
  and stall the backfill.

## 8. Risks & Mitigations

**R1: A sensitive domain misses the denylist and its text leaves the host.**
- Local, single-label and non-http hosts are hard-denied.
- `DEFAULT_DENY` ships with the code.
- `--dry-run` works before enabling.
- `allow` is available for the cautious.

**R2: Repeated charges for failing pages.**
- Content failures are recorded once (D13).
- Transport failures are bounded by the breaker and retried next run.

**R3: The provider stores or trains on the text.**
- The user checks retention terms before adding a provider (DEC-002).
- The endpoint and model are explicit config, and every record names its
  endpoint.

**R4: Prompt or model drift.** Each record stores `model` and
`prompt_version`.

**R5: Prompt injection from page content.**
- The model has no tools, so the effect is confined to the digest text.
- Page text is fenced as data in the prompt.
- Digests are documented as untrusted for downstream agents.

## 9. Quality Engineering & Validation

**Pure units (TDD):**
- `parse_config`:
  - a valid config;
  - a missing model;
  - an unknown key at each level;
  - a literal `api_key`;
  - a non-https endpoint;
  - a non-normalisable domain entry;
  - an IDN entry normalised to punycode.
- `gate`:
  - every reason in the table;
  - a trailing dot, mixed case, an IDN host, and an IDNA error (`bad_url`, not
    a crash);
  - `evilbank.com` vs `bank.com`;
  - IPv4/IPv6 literals, a single-label host, and `*.local`, including when
    `allow` is set;
  - `allow` cannot pass a denied host;
  - `file://`, and a URL with no host.
- `DEFAULT_DENY`:
  - every entry is already normalised;
  - the defaults apply when `deny` is omitted.
- `pending`:
  - a latest row that is gated or done means no fallback;
  - mixed tz offsets and `Z` suffixes;
  - newest-first ordering.
- `build_request`:
  - only the host, title and text appear (the URL path and userinfo are
    absent);
  - truncation sets `truncated`;
  - the schema shape and `require_parameters`;
  - the page sits inside the delimiter.
- `parse_digest`: success, and each `Failure` kind.

**Store:**
- the record round trip in `tmp_path`;
- the fail marker counts as done;
- idempotence (I4).

**Run level**, with an injected fake transport:
- no config, or not enabled: no lock file and no calls (I3);
- a dry run with `enabled = false` and no key: verdicts printed, no calls, no
  writes;
- a gated page never reaches the transport (I1);
- a content failure writes a marker and the run continues;
- `ProviderUnavailable` aborts with exit 1;
- 3 consecutive transport failures abort;
- the lazy walk stops at `limit`;
- the exit codes match the §5.2 table.

**Client**, against a local `http.server` fixture:
- a 302 raises `ProviderUnavailable` and the target is never contacted;
- a 429 with a large `Retry-After` is capped and retried;
- a 401 is fatal;
- with a bogus `HTTPS_PROXY` set, the connection still goes direct.

**I5:** a `caplog` test across failing and succeeding runs finds no page text
and no key in the logs.

**I2 tripwire:**
- An AST walk over `panopticon/**.py` checks the I2 module list.
- It is a tripwire, not a proof: `asyncio.open_connection` would evade it.
- With D10 it needs no exemptions.

**D6 behaviour gate:** the content, store, segmentizer and git-poller suites
stay green unchanged.

**VH (verified by a human):** one live run against OpenRouter on a handful of
pages, then a manual read of the records (OQ-1).

**Docs:**
- **README:** replace "No network calls" (lines 11 and 119) with the DEC-002
  statement, and add the binary table row, config, how to enable it, and that
  digests are untrusted.
- **`docs/privacy.md`:** state the egress, and exactly what leaves the host
  (I1).

## 10. Review Notes

**Round 1** (2026-10-01, adversarial subagent; the codex MCP was unavailable).
All 17 findings were verified and accepted:
- gate holes (`file://`, the `"unknown"` domain, trailing dot);
- unredacted body links → D9;
- reading `length` by `stat` was wrong;
- selection order and the fallback;
- the `response_format` shape;
- the circuit breaker and `Retry-After` cap;
- strict config;
- client hygiene and I5;
- dead network code → D10;
- I3 vs the lock;
- index loss;
- D5 wording;
- prompt injection → R5;
- discrete `quality_score`;
- the egress ledger and `StageStore`;
- naming (`settings.py`).

**Round 2** (2026-10-01, a fresh adversarial subagent). All 13 findings and the
3 proposed cuts were verified and accepted:
- **Blocker:** a single `mode` + `domains` list inverted its meaning across
  modes → D4 recast as deny-always + allow-narrows.
- **Major:** deterministic content failures would wedge the breaker and stall
  the backfill → D13, fail markers.
- **Major:** dry-run was impossible before enabling → `--dry-run` ignores
  `enabled` and the key.
- **Major:** the URL (path, userinfo) was being sent → D11, host only; I1 lists
  exactly what leaves the host.
- **Minor:**
  - single-label hosts → `local_host`;
  - IDNA errors and config-entry normalisation;
  - `DEFAULT_DENY` gets a home and tests, with contents settled in the plan;
  - the exact urllib opener wiring, with redirects fatal;
  - trafilatura removed as a dead dependency, plus the README lines;
  - a full exit-code table;
  - the `exclusive_lock` contract;
  - wording on the `"unknown"` domain and `captured_at`.
- **Cuts taken:**
  - the key-shaped-field rule (unknown-key rejection covers it);
  - `use_env_proxy` (always `ProxyHandler({})`);
  - the digest index and `reconcile_index` (D12);
  - lazy `.json` reads were adopted.
