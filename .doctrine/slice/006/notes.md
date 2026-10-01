# Notes SL-006: panopticon-digest: opt-in page digest over the content store

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## Design process (2026-10-01)

- Sliced from IDE-002; governed by DEC-002. Design locked after three adversarial
  rounds (fresh general-purpose subagents; the codex MCP was down). Findings and
  dispositions are in design §10.
- User decisions: D1 (gate + digest only), D2 (stdlib urllib), D3 (TOML + env
  secrets), D4 (deny-always, allow-narrows), D10 (delete extractor), D15 (move
  amo.py to tools/).
- Corpus facts in design §2 are aggregates only. Keep it that way: never commit
  URLs or titles from the user's content store.
- A pre-existing lint failure (unsorted imports, tests/test_git_poller.py) was
  fixed separately in 4120613.
- IDE-002's body still lists ISS-003 as open, but ISS-003 is resolved
  (899b6b8). Left unedited.
- Model choice (OQ-1) is pending web-agent research on providers; only PHASE-04
  needs it.

## PHASE-01 groundwork (2026-10-01)

- `panopticon/fsutil.py` is the single atomic-write / flock implementation.
  Four atomic-write copies migrated, not three: `firefox_host/install.py` was
  missed by design §2. `exclusive_lock` does not mkdir; callers own directories.
- `panopticon/settings.py`: `config_dir()`, `load_toml()`. `load_toml` raises
  `OSError` / `TOMLDecodeError`; the digest shell decides "no config → exit 0"
  by checking existence first.
- `tools/amo.py` (dev tool, outside the wheel); pytest `pythonpath = ["."]`.
- I2 tripwire: `tests/test_network_boundary.py`. It whitelists
  `panopticon/digest/client.py` by path; third-party libraries are not covered
  (trafilatura would have evaded it — removed anyway).
- `uv lock` works in the jail. The repo is not ruff-formatted and `just check`
  has no format gate; format new files only.

## PHASE-02 pure core (2026-10-01)

Modules: `panopticon/digest/{gate,config,select,prompt}.py`. Dependency
direction: `config → gate`, `prompt → config`, `select → gate`.

Decisions made within the design (none change what leaves the host):
- `GateConfig` lives in `gate.py` (the gate owns its policy type; config only
  builds it). `Pass(host)` carries the normalised host, the one I1 allows out.
- `normalise_host` is stricter than the design text: labels must match
  `[a-z0-9_-]+`, or the whole host must be an IP literal. Without this, a deny
  entry like `https://bank.com` or `bank.com/x` would normalise and silently
  never match. Weird URL hosts become `bad_url`, which is fail-closed.
- `local_host` also covers `*.localhost` (RFC 6761 loopback).
- An empty `allow = []` is accepted and passes nothing (fail-closed).
- `pending` is total: a row with a non-str url/content_hash, a non-numeric
  quality, or an unparseable or naive `captured_at` gets the new reason
  `bad_row`, sorted last. The user confirmed this on 2026-10-01, and design
  §5.2 is amended to match. The corpus has none today (aggregate: 2462 rows, all
  well-typed; 36 `Z` and 2426 numeric offsets; 8 `None` titles).
- `pending` precedence per row: `bad_row` → `superseded` → `done` → gate. Ties
  on `captured_at` go to the later index row. It returns every row judged,
  newest first; candidates are the `Pass` rows, and the shell re-calls `gate`
  with the length to apply `too_short`.
- Config defaults: `enabled = false`, `max_pages_per_run = 50`; `[gate]`
  optional; `[digest]` required (for `model`); `endpoint` and `api_key_env`
  default to the design-example OpenRouter values. `ConfigError` messages name
  the key, never the value.
- `Page(host, title, text)` has no URL field, so I1 holds by type. The host,
  title and text all sit inside `<page>…</page>`. `_defang` breaks any
  `<page`/`</page` (any case, inner whitespace) in the title or text by
  appending `_`. `input_chars` counts the truncated text before defanging.
- `parse_digest(bytes)`: an `error` key counts only when it is non-null.
  `content` that is null or non-str gives `not_json`, not `provider_error`.
  `RecursionError` from deep nesting is caught. `PROMPT_VERSION = "1"`.
- Purity (EX-1): `tests/test_digest_purity.py` is an AST tripwire over the four
  modules. It flags impure imports, `.now()/.today()/.utcnow()` calls, and
  bare `open`, `input` and `print`. It shares `tests/ast_imports.py` with
  the I2 tripwire.

For PHASE-03:
- `Reason` holds the gate reasons plus `bad_row`, `superseded` and `done`, so
  dry-run can print one enum.
- The record needs `host` (from `Pass`), `input_chars` and `input_truncated`
  (from `Request`), plus the `Digest` fields. `Failure.kind` feeds the D13/D14
  content-vs-provider split: `provider_error` is a provider failure, and every
  other kind is a content failure.

## PHASE-03 impure shell (2026-10-01)

Modules: `digest/{store,client,__main__}.py`; `panopticon/cli.py`;
`systemd/digest.{service,timer}`; console script `panopticon-digest`.

Shared seams (no parallel implementation):
- `ingest/content.py` gains public `shard_path(root, sha, suffix)` and
  `read_index(content_root)`. `ContentStore` and `StageStore` share the layout;
  `_read_index` is gone.
- `panopticon/cli.py`: `log_level` / `configure_logging`. Four entrypoints had
  copies, in two spellings; all now call the shared one.

Decisions made within the design:
- `StageStore.put(sha, record)` / `put_failure(sha, marker)` take the SHA
  explicitly. The §5.3 marker has no `content_hash`, so the file name is the key.
- Streaks count failures of each class since the last success; a success resets
  both. This is stricter than "consecutive", so it aborts sooner, never later.
- Every abort discards held markers. §5.4 requires this for the content breaker.
  For `ProviderUnavailable` and the transport breaker it is the conservative
  reading of "mark only what's proven": those pages are re-sent next run.
- `PageRejected` marker: `kind = "page_rejected"` plus `status`.
- The client never sees the SHA. It logs `attempt n/4` with the status or
  exception class name; the shell logs the SHA with the outcome.
- Backoff with no `Retry-After`: `2**(attempt-1) + jitter` seconds. An HTTP-date
  `Retry-After` is ignored (backoff is used instead).
- Dry-run output: `verdict<TAB>sha` per row; a pass row adds
  `input_chars<TAB>host<TAB>title` (whitespace flattened). A final line gives
  per-verdict counts, which PHASE-04 can quote as aggregates. Only cheap-gate
  passes have their `.json` read: `too_short` is the last rule, so the output
  is identical. A missing `.json` is logged and skipped, not printed.
- Cert-failure test: `tests/fixtures/selfsigned-localhost.pem` is a committed
  throwaway key and cert (100-year expiry). The nix sandbox has no openssl, and
  the stdlib test certs are not shipped.
- `digest.service` has no `network-online.target` ordering: that is a system
  target and has no effect in a user unit.

For PHASE-04:
- Corpus dry-run: `panopticon-digest --dry-run --config <cfg>` with a config
  holding any `model`. The last stdout line holds the counts. Commit only
  aggregates.
- The README needs: the binary table row, config, enabling the timer, the
  `digest.env` path note, and that digests are untrusted text.
