# IDE-004: digest: model flags private / self-authored surfaces to audit the deterministic gate

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Origin: SL-006 VH-1. A LinkedIn compose page (the user's own draft) passed
the gate and was sent. Fixed deterministically in `DEFAULT_DENY`, but the
miss showed the gate has no feedback loop.

Idea: the model already reads each page, so it can also return a field
that marks a private or self-authored surface (draft or compose page,
private message, account page, personal data). A local periodic audit
reads the flagged records and proposes new `deny` entries.

Constraints:
- Advisory only. It is detection after egress: the page has already left.
  It never gates, because a model never decides whether text may reach a
  model (SL-006 design).
- Flag narrowly. Public user-generated content (HN, reddit threads)
  would flood a plain "UGC" flag; the target is *private or
  pre-publication* content. Use a closed reason enum, not a free bool.
- Best placed in stage-2 triage (already a typed classification and
  re-runnable alone), not the digest schema: a digest schema change bumps
  `prompt_version` and forces re-digest.
- False negatives are expected. A page can also suppress its own flag via
  injection, which is low stakes here. Treat a missing flag as no evidence.
- The audit stays local: it reads stored records only, no egress.
