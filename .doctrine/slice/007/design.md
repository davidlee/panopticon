# Design SL-007: digest: closed entity-type vocabulary

<!-- Reference forms (.doctrine/glossary.md § reference forms): entity ids padded
     (SL-020, REQ-059, ADR-004); doc-local refs bare — OQ-1 (§6), D1 (§7),
     R1 (§10), Q1. -->

## 1. Design Problem

`entities[].type` is free text. The prompt only suggests examples, so the
model drifts between near-synonyms and invents types. Consumers cannot group
on it.

## 2. Current State

`panopticon/digest/prompt.py`:
- `_ENTITY` schema: `type: {"type": "string"}`.
- `_SYSTEM`: "notable people, organisations, projects, products and places,
  each with a short lowercase type such as "person" or "project"".
- `Entity(name: str, type: str)`; `_is_entity` checks only that both are
  strings. `PROMPT_VERSION = "1"`.
- 3 records exist under `digest/` (SL-006 VH-1), all version 1.

## 3. Forces & Constraints

- Strict `json_schema` + `require_parameters` (SL-006) means the provider
  enforces an `enum`; `parse_digest` stays total and defensive regardless.
- A JSON-schema `enum` lists values only; meanings must live in the prompt.
- The model sees `text_content` only (SL-006 D11): links are invisible, so
  a `work` is something *named* in the text.

## 4. Guiding Principles

- One source of truth for the vocabulary: the schema enum, the parser and
  the type all derive from one `StrEnum`.
- Split by what a thing *is*, not by licence or business model (the
  project/product line is where VH-1 drifted).

## 5. Proposed Design

### 5.1 System Model

No new components. `prompt.py` gains `EntityType(StrEnum)`; everything else
derives from it.

### 5.2 Interfaces & Contracts

Vocabulary (user, 2026-10-02):

| type           | meaning (as stated in the prompt)                                           |
|----------------|-----------------------------------------------------------------------------|
| `person`       | a named individual                                                          |
| `organisation` | a company, institution, community, standards body or team                   |
| `place`        | a geographic location                                                       |
| `software`     | a program, library, OS, kernel module, service or protocol implementation  |
| `hardware`     | a physical device, component or machine                                     |
| `work`         | a named authored piece: article, blog post, paper, book, standard, talk, film |
| `concept`      | an idea, technique, field or problem                                        |
| `event`        | a named occurrence: conference, release, incident, vulnerability            |
| `other`        | anything notable that fits none of the above                                |

- `_ENTITY.properties.type` = `{"type": "string", "enum": [<EntityType values>]}`.
- `_SYSTEM` lists each type with its meaning and states: "List things the
  page names; never the page itself."
- `Entity.type: EntityType`. `_is_entity` additionally requires the type to
  be a vocabulary value; otherwise the reply is `bad_shape` (D3).
- `PROMPT_VERSION = "2"`, then `"3"` with D5. Records serialise the type as
  its string value.

### 5.3 Data, State & Ownership

Record shape unchanged; `entities[].type` is now always a vocabulary value
for `prompt_version` 2.

### 5.4 Lifecycle, Operations & Dynamics

Migration (operational, user-approved 2026-10-02): delete the 3 version-1
records by hand; the next run re-digests them.

### 5.5 Invariants, Assumptions & Edge Cases

- **I1:** every version-2 record's entity types are in `EntityType`.
- An empty `entities` list remains valid.

## 6. Open Questions & Unknowns

None.

## 7. Decisions, Rationale & Alternatives

- **D1: the 9-type kind-of-thing vocabulary** (user). Rejected: a 5-type
  minimal set (loses software/hardware); keeping project/product (the
  observed drift line).
- **D2: definitions in the prompt; the page is never its own entity.**
  An enum cannot carry meanings.
- **D3: out-of-vocabulary type → `bad_shape`**, consistent with every other
  schema mismatch. Rejected: mapping to `other`, which would hide a provider
  that ignores the enum. The SL-006 breakers already stop a run whose model
  fails every page before any marker is written.
- **D4: no re-digest machinery.** Delete the 3 records by hand (user).
- **D5: dial back over-extraction by guidance, not enforcement** (user,
  2026-10-02, after VH-1 on prompt v2 listed up to 23 entities per page,
  including keybindings, file names and aliases). The prompt asks for at most
  `ENTITY_LIMIT` (10) of the most significant entities, skips commands,
  keybindings, file names, config keys and the hosting site, and lists each
  entity once under its most common name. `PROMPT_VERSION` 3. The parser
  does not enforce the cap: a small model's overrun must not become a failed
  page. Rejected: `maxItems` in the schema (same failure mode, and provider
  support for it under strict mode is uneven).

## 8. Risks & Mitigations

- **R1:** a provider that does not enforce `enum` yields `bad_shape` for
  pages with an off-list type. Mitigation: `require_parameters` routes only
  to providers that support strict schemas; the content breaker bounds a
  bad run; VH-1 re-checks with the real model.

## 9. Quality Engineering & Validation

- The schema enum equals the `EntityType` values (one source).
- `parse_digest`: each vocabulary value parses; an off-list type is
  `bad_shape`.
- The system prompt names every type and the never-the-page rule.
- `PROMPT_VERSION == "2"`.
- VH: the 3 re-digested records use only vocabulary types.

## 10. Review Notes

Small, single-module change; self-reviewed against SL-006's prompt contract
(I1 untouched: `Page` and `build_request`'s inputs are unchanged).
