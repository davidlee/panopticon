# IMP-002: digest: closed entity-type vocabulary

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Origin: SL-006 VH-1. The digest prompt only suggests entity types ("short
lowercase type such as person or project"), so gpt-4.1-mini drifts
(`software` vs `project`; `hardware audio device`, `kernel module`). That
hurts grouping for SATAN consumers (tagging, related reading).

Options: an `enum` in the strict json_schema (bumps `prompt_version`, so
existing records re-digest or carry the old type); or map types after the
fact at read time (no re-digest). Decide alongside stage-2 triage's
taxonomy so the two vocabularies agree.
