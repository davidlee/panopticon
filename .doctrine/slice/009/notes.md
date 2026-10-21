# Notes SL-009: digest: scheduled run through the LLM gateway

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## Harvest
<!-- single-copy: updated in place each harvest; ids only, never restated content -->
fresh-as-of: 2026-10-22 · close · e58d19c

### Produced

### Learned

- PHASE-01: design §5.2 says `fstat` stops a FIFO blocking the run, but
  `open()` blocks on a writerless FIFO before `fstat` runs. The key file is
  opened `O_NONBLOCK` (test: `..._key_file_is_a_fifo`).
- PHASE-01: "inner whitespace" (VT-2) is the existing check: control
  characters and leading/trailing whitespace. An inner plain space is
  printable and passes; left as designed ("the existing check applies").

- PHASE-03 (2026-10-22), live, through the gateway with
  `openrouter/openai/gpt-4.1-mini`:
  - VH-0: `--limit 3 -v` → digested=3, failure_markers=0,
    provider_failures=0. The strict `response_format` survives LiteLLM.
    A new record carries the gateway endpoint and model.
  - VH-1: `systemctl --user start panopticon-digest` → Result=success,
    digested=50 (the `max_pages_per_run` cap), no failures; the timer is
    listed with a next run.
  - VH-2: `--audit` → exit 0, one summary line, same shape as before.

### Open

- Backlog: ~120 gate-passing pages remain after VH-1; daily runs of 50
  clear it in a few days, or a manual `--limit` run sooner.
- `~/flakes` `features/attention/behaviour.nix` header still says the
  panopticon input is `path:`; it is `github:`.

## Spike: the gateway and the routing pin (2026-10-20)

Probes against the gateway (`http://127.0.0.1:4000/v1`) with the
`panopticon-digest` client key, model `openrouter/qwen/qwen3.8-flash`. The
pass-through result does not depend on the model.

Evidence:
- `provider: {only: ["no-such-provider-xyz"]}` → 404 carrying OpenRouter's own
  error ("your request's provider.only preference permits only: …").
- `provider: {sort: "not-a-valid-sort"}` → 400, OpenRouter's
  "provider.sort: Invalid input".
- `provider: {require_parameters: true, allow_fallbacks: false}` (the digest's
  pin) → 200.
- After two consecutive upstream 4xx responses, the next request got a 429
  "No deployments available … Try again in 5 seconds", `Retry-After: 5`
  (LiteLLM router cooldown). A request 10 s later succeeded.
- Unknown key → 401. Model off the key's allow-list, or not served → 403
  ("…: model … not allowed"). Budget exhausted → 401
  (`~/flakes/features/agents/gateway/gateway_hooks.py`, `authenticate`).

Inference:
- LiteLLM forwards the `provider` block to OpenRouter unchanged, so the
  SL-006 pin survives the gateway. `prompt.py` needs no change, and
  gateway-side `params` are not needed.
- Cooldown 429s are absorbed by `client.post_json`: 429 is retried and
  `Retry-After` is honoured (capped at 60 s).
- Budget exhaustion and a bad key map to `ProviderUnavailable` (fatal for
  the run), which is correct.
- A 403 maps to `PageRejected` (a per-page content failure). Through the
  gateway, 403 also means misconfiguration (model not on the key). That
  costs at most `CONTENT_BREAKER` (5) requests before the run stops, and
  the markers are dropped because nothing succeeded. The page text only
  reaches the local gateway, so this is acceptable; reclassifying 403 would
  conflict with OpenRouter's use of 403 for moderation refusals.
- The key as issued allows `deepseek-flash`, `openrouter/qwen/qwen3.8-flash`
  and `openrouter/z-ai/glm-5.3-flash`. Neither the key nor the gateway
  allows `openrouter/openai/gpt-4.1-mini` yet.
