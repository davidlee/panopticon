# Design SL-009: digest: scheduled run through the LLM gateway

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

The digest has never run on a schedule. Its units ship in `systemd/` but the
user's units come from `~/flakes`, which does not define them. It also holds
its own OpenRouter key, while the machine now has a local LLM gateway (LiteLLM,
`~/flakes/agents/gateway.nix`) that holds provider keys and issues per-client
keys. Route the digest through the gateway and run it daily.

## 2. Current State

- `config.py`: `endpoint` must be `https://` with a host (`_is_https_url`);
  default OpenRouter. The key comes only from the environment variable named
  by `api_key_env` (default `OPENROUTER_API_KEY`); a literal `api_key` is an
  unknown key.
- `__main__.run`: reads `env[api_key_env]`; unset → exit 2; leading/trailing
  whitespace or control characters → exit 2 (http.client would echo the key).
- `client.post_json`: no redirects, no proxies, verified TLS. 429 and 5xx
  retry honouring `Retry-After` (cap 60 s); 401/402/3xx fatal; other 4xx a
  per-page rejection.
- `prompt.build_request` sends the OpenRouter routing pin
  `provider: {require_parameters: true, allow_fallbacks: false}` (SL-006).
- Records carry `endpoint` and `model` as the egress ledger.
- Gateway: `http://127.0.0.1:4000/v1` (socket-activated relay on loopback);
  model names `<gateway provider>/<upstream id>` (DEC-069); per-client key
  files under `~/.config/llm-gateway/keys/<client>`, each with a model
  allow-list and a USD budget. The `panopticon-digest` key exists.
- Spike (notes.md, 2026-10-20): the gateway forwards the `provider` block to
  OpenRouter unchanged. Bad key and exhausted budget → 401; model off the key
  → 403; after upstream 4xx the router may answer 429 `Retry-After: 5`.

## 3. Forces & Constraints

- **The https rule protects the key and page text on a network.** Loopback
  has no network hop; anything else still needs TLS.
- **Secrets never in the config file.** A path to a key file is not a secret.
- **Fail closed, exit 2,** on any key or config problem; never log the key.
- **No private data in the repo** (SL-008): the user's `digest.toml` stays
  out of git; docs use example values.
- Minimal surface: no change to the prompt, schema, gate or client.

## 4. Guiding Principles

- Ride existing seams: `_field` validators, the existing key checks in `run`.
- Pure config, impure shell: config validates strings; reading the file and
  expanding `~` happen in `__main__`.

## 5. Proposed Design

### 5.1 System Model

```
timer (daily) ─▶ panopticon-digest ──http, loopback──▶ LLM gateway ──https──▶ OpenRouter
                   key: api_key_file                    holds provider key      pin honoured
                   (~/.config/llm-gateway/keys/…)       may log prompts locally
```

### 5.2 Interfaces & Contracts

**Config** (`[digest]`):

| key            | rule                                                                 |
|----------------|----------------------------------------------------------------------|
| `endpoint`     | `https://<host>…`, or `http://<loopback IP literal>…` (D1); no      |
|                | userinfo (`@`), a valid port if any                                  |
| `api_key_env`  | unchanged                                                            |
| `api_key_file` | new; non-empty string, absolute or `~/…` (D2)                        |

At most one of `api_key_env` / `api_key_file`; both → `ConfigError`. Neither
→ `api_key_env = "OPENROUTER_API_KEY"` (today's default).

`ProviderConfig` replaces `api_key_env: str` with
`key_source: KeyEnv | KeyFile` (frozen dataclasses, one field each), so `run`
cannot read both.

The `api_key_file` shape check is plain string ops (`startswith("/")` or
`"~/"`): `config.py` is in the purity tripwire's pure set, which bans `os`
and `pathlib` (`tests/test_digest_purity.py`).

**Key resolution** (`__main__`): one function,
`_api_key(source, env) -> str | None`, logs and returns `None` on failure
(→ exit 2). It runs where the env read runs today: after `--dry-run` and the
`enabled` check, so a disabled config never needs a key.
- `KeyEnv(name)`: as today.
- `KeyFile(path)`: `Path(path).expanduser()`, then open it and require a
  regular file (`fstat`, so a FIFO cannot block the run); read at most 4 KiB
  as UTF-8; more than that is an error. Any `OSError`, `UnicodeDecodeError`
  or `RuntimeError` (unresolvable `~`) logs the path and
  `type(e).__name__` only: never `str(e)` or a traceback, since a decode
  error carries the raw bytes. One trailing `\n` is removed (the gateway
  writes key + `\n`).
- The existing whitespace/control check then applies to both; its message
  names the source ("environment variable X" / "key file P"). CRLF and a
  BOM fail it, closed.

**Units** (`~/flakes/features/attention/behaviour.nix`): `panopticon-digest`
service (oneshot, absolute store path, `-v`, `TimeoutStartSec=2h`) and timer
(`OnCalendar=daily`, `Persistent`, `RandomizedDelaySec=30min`, `WantedBy
timers.target`), alongside `panopticon-git` / `-segmentize`. No
`EnvironmentFile`.

**Gateway** (`~/flakes/agents/gateway.nix`): add `openai/gpt-4.1-mini` to the
OpenRouter `routed` list. The user adds it to the `panopticon-digest` key.

**User config** (private, not committed):
```toml
[digest]
endpoint = "http://127.0.0.1:4000/v1/chat/completions"
model = "openrouter/openai/gpt-4.1-mini"
api_key_file = "~/.config/llm-gateway/keys/panopticon-digest"
```

### 5.3 Data Model

No record change. New records carry the gateway endpoint and the gateway
model name, which names the upstream provider (DEC-069). Existing records keep
`openai/gpt-4.1-mini` at OpenRouter: the same model, so no re-digest.

## 6. Open Questions

None open.

- **OQ-1 (resolved)** Cadence. Evidence (dry run, 2026-10-21): 175 pages pass
  the gate and await a digest, accumulated since the 2026-10-02 backfill,
  about 10 a day. Daily with `max_pages_per_run = 50` keeps up; a manual
  `--limit` run can clear the backlog.

## 7. Decisions

- **D1 Loopback http.** Accept `http` only when the host parses as an IP
  address with `is_loopback` (127.0.0.0/8, `::1`, and IPv4-mapped
  `::ffff:127.x`). `localhost` is refused: a name is resolved, and this rule
  must not depend on resolution (amends the scope, which listed it). A zone
  id (`%`) is refused. For any scheme, userinfo (`@` in the netloc) is
  refused: `urlsplit` reports the host after `@`, but urllib connects to the
  whole `user@host` string, and the userinfo would also land in every
  record's `endpoint`. The port is read inside the `try`, so a bad port is a
  config error (exit 2), not a run of transport failures.
  `_is_https_url` becomes `_is_endpoint_url`; the error text says
  "an https:// URL, or http:// to a loopback IP". The client needs no change:
  its opener already handles http, and proxies stay ignored.
  - Alt: drop the rule entirely. Rejected: a typo like `http://openrouter.ai`
    would send the key in cleartext.
- **D2 Key from a file,** named in config. The gateway issues a raw key file.
  - Alt: a shell wrapper exporting `$(cat file)`. Rejected: the key enters a
    command line and the unit grows logic.
  - Alt: systemd `LoadCredential=`. Rejected: ties the digest to systemd and
    still needs a file reader.
  - Alt: require mode 0600 on the file, as ssh does. Deferred: the gateway
    CLI writes the file; not worth the code now.
- **D3 Routing pin unchanged.** The spike shows it reaches OpenRouter.
- **D4 403 stays a per-page rejection.** Through the gateway a 403 also
  means "model not on the key", but OpenRouter uses 403 for moderation
  refusals. A misconfigured key costs at most `CONTENT_BREAKER` (5) requests,
  only to the local gateway, and no markers persist without a success.
- **D5 Units live in `~/flakes`;** `systemd/digest.*` stays as the reference
  for non-Nix installs, with its comment updated to mention `api_key_file`.
  Its `EnvironmentFile=-` line stays (optional, still valid for env keys).
- **D6 Gateway prompt logging** is recorded in `docs/privacy.md` as a fact
  (user, 2026-10-20): any stored prompts stay in a local sqlite database.
- **D7 What privacy.md says about the gateway hop:**
  - Loopback http authenticates no server. The port is held by a
    socket-activated relay; if the relay is down, another local process could
    bind it and receive the key and page text. Accepted for a single-user
    machine. The gateway's user-owned unix socket is the authenticated
    alternative, if ever wanted (urllib has no unix-socket transport; a
    follow-up, not this slice).
  - Records name the gateway endpoint and the gateway model name. Which
    upstream received the text follows from `~/flakes` config and the
    DEC-069 naming convention, not from the record alone.

## 8. Impact & Changes

| area        | change                                                                |
|-------------|-----------------------------------------------------------------------|
| `config.py` | D1 validator; `api_key_file`; `KeyEnv`/`KeyFile`; exclusivity; docstring |
| `__main__`  | `_api_key`; `run` uses it; module docstring ("nothing enables the timer") |
| `systemd/digest.{service,timer}` | comments only ("shipped disabled", key source)   |
| tests       | `ProviderConfig` callers: `test_digest_prompt.py`, `test_digest_config.py`, `test_digest_main.py` |
| README      | config example; scheduling paragraph (flakes/HM or units; key file)   |
| `docs/privacy.md` | endpoint rule; key source; the gateway hop and its local logging |
| `~/flakes`  | `behaviour.nix` units; `gateway.nix` model entry                      |

## 9. Verification

- **VT config:** http to `127.0.0.1`, `127.1.2.3`, `[::1]`,
  `[::ffff:127.0.0.1]` accepted; http to a public host, `localhost`,
  `0.0.0.0` and `[::1%lo]` rejected; userinfo rejected for http and https;
  a bad port rejected; `api_key_file` accepted (absolute and `~/`); a
  relative one rejected; both key fields → error naming the key, not the
  value.
- **VT main:** key file read and sent as the bearer; one trailing newline
  stripped; missing file, a directory, an oversize file → exit 2; non-UTF-8
  bytes → exit 2 and the logs hold neither the bytes nor the key; inner
  whitespace or CRLF → exit 2 with a message naming the key file; a disabled
  config with a missing key file → exit 0; the env path unchanged (existing
  tests stay green apart from the `ProviderConfig` constructor).
- **VH-0 (before enabling the timer):** `panopticon-digest --limit 3 -v`
  through the gateway with `openrouter/openai/gpt-4.1-mini` digests 3 pages.
  The spike probed only the `provider` block; this proves LiteLLM passes the
  strict `response_format` and `max_tokens` through and the reply parses.
- **VH-1:** after `home-manager switch`, `systemctl --user start
  panopticon-digest` digests through the gateway (journal shows
  `digested=N`, N > 0); the timer is listed with a next run; a record shows the
  gateway endpoint and model.
- **VH-2:** `panopticon-digest --audit` runs clean or reports as before.

## 10. Risks

- **R1** Gateway down at run time: connection refused is a transport
  failure; the provider breaker stops the run; the next run retries.
- **R2** Budget exhausted: 401 is fatal for the run; the journal shows it.
  Nothing alerts the user.
