# IMP-003: move shard_path from ingest.content to fsutil

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Origin: SL-006 close-out review. `digest/store.py` imports `shard_path`
from `panopticon.ingest.content`, so the digest stage depends on the ingest
module for a generic path helper (`<root>/<sha[:2]>/<sha><suffix>`).
`fsutil` is the neutral home; both stores would import it from there.
Small and behaviour-preserving: the existing suites are the proof.
