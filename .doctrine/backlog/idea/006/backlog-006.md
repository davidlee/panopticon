# IDE-006: digest: trial a non-OpenRouter model through the gateway

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Origin: SL-009 scoping (user, 2026-10-20). SL-009 keeps the digest on
OpenRouter (`openai/gpt-4.1-mini`), routed through the local LLM gateway.
Moving off OpenRouter is deferred here to keep SL-009 small.

Candidates:
- Fireworks: `fireworks/models/glm-5p3-flash`,
  `fireworks/models/deepseek-v4p1-flash`.
- DeepSeek direct (`deepseek-flash`, the user's default model elsewhere).
  Unverified whether it honours `response_format` json_schema with
  `strict: true`.

Questions:
- Does the provider honour strict json_schema for the chosen model? On
  OpenRouter, `provider.require_parameters` guarantees it; elsewhere it must
  be checked directly.
- The OpenRouter-only `provider` request block must not reach other
  providers (see SL-009 for how it is handled).
- A model change is a prompt-quality change: re-run the SL-007/SL-008 VH
  checks (entity extraction, `private_surface`) before switching.
