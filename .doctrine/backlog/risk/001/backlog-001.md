# RSK-001: Content store has no retention: full page bodies accumulate indefinitely

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Found 2026-09-29.

`segmentizer/retention.py:5-9,44-45` prunes raw (7 d) and segments (90 d);
nothing prunes `~/.local/state/behaviour/content/` (~2379 pages, full text
+ HTML + markdown, since 2026-05-31).

Harm: unbounded disk growth, and an ever-growing archive of full page bodies
(incl. anything sensitive that passed the redaction filters) — contrary to the
bounded retention the rest of the store keeps.

Mitigation options: age-based prune; keep bodies for N days but digests
(satan IDE-001) longer; exempt bookmarked URLs. Decide alongside ISS-002.
