# digest: scheduled run through the LLM gateway

## Context

SL-006 shipped `panopticon-digest` with `systemd/digest.{service,timer}`,
disabled. The user's units are installed by `~/flakes`
(`features/attention/behaviour.nix`), which does not define the digest
units, so nothing runs the digest on a schedule. Runs to date were manual
(SL-008 backfill). There is no `digest.env`, so no key either.

Since then `~/flakes` added a local LiteLLM gateway (`agents/gateway.nix`):
an OpenAI-compatible endpoint at `http://127.0.0.1:4000/v1`, holding the
provider keys, issuing per-client keys as files under
`~/.config/llm-gateway/keys/<client>`. The digest should use it rather than
hold an OpenRouter key itself.

Decisions taken while scoping (user, 2026-10-20):
- Do the gateway move and the scheduler together.
- Stay on OpenRouter, `openai/gpt-4.1-mini`; moving provider/model is IDE-006.
- Plain http is acceptable to a loopback endpoint.
- The gateway may store prompts in its local sqlite db. That keeps page text
  on the machine and does not materially change the privacy model; record
  it as a fact in `docs/privacy.md`.
- The user issues the gateway client key.

## Scope & Objectives

- **Spike:** does LiteLLM forward the request's `provider` block
  (`require_parameters`, `allow_fallbacks: false`) to OpenRouter, drop it,
  or reject it? If dropped, can the gateway's per-model `params` (DEC-070)
  supply it instead? The pin is an SL-006 guarantee; it must not be lost
  silently.
- **Endpoint rule:** `https://` anywhere, or `http://` only to a loopback
  IP (`127.0.0.0/8`, `::1`). `localhost` is refused (design D1). Other http
  stays a config error.
- **Key from file:** read the key from a file (the gateway's per-client key
  file); still never from the config file itself.
- **Gateway model list** (`~/flakes/agents/gateway.nix`): serve
  `openrouter/openai/gpt-4.1-mini`.
- **Scheduler** (`~/flakes/features/attention/behaviour.nix`):
  `panopticon-digest` service + timer, following the existing panopticon
  units (absolute store path, `OnCalendar`, `Persistent`), keeping the
  `TimeoutStartSec` backstop.
- `docs/privacy.md`, README: the egress now goes through the gateway.
- **VH:** one scheduled run end to end through the gateway, then `--audit`.

## Non-Goals

- Changing provider or model (IDE-006).
- Prompt or schema changes.
- Gateway changes beyond the model list entry.

## Summary

Small changes in `panopticon/digest/config.py` (endpoint rule, key source)
and `__main__.py` (key read), possibly `prompt.py` (routing pin, per spike);
two `~/flakes` edits; docs.

## Follow-Ups

- IDE-006: trial Fireworks / DeepSeek models.
- Whether the repo's `systemd/digest.*` units remain the source of truth or
  become reference only once `~/flakes` defines them (decide in design).
