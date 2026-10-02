# IDE-005: digest gate: wildcard path segments in deny entries

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Origin: SL-008, the first `--audit` after the backfill. A code host's
per-repo settings page was flagged. A deny entry is a host plus a literal
path prefix (`gate._denied`), so `/<owner>/<repo>/settings` can only be
denied one repo at a time, or by denying the whole owner. The same shape
recurs elsewhere: dashboard paths with an account id first, then the
private part (`/<account-id>/…`).

Idea: let a path segment in a deny entry be `*`, matching exactly one
segment, e.g. `github.com/*/*/settings`, `github.com/*/*/settings/…`.

Constraints:
- Keep matching segment-wise on the normalised path (`gate.normalise_path`),
  so it still fails closed. `*` matches one non-empty segment; no `**`, no
  partial-segment globs. Literal entries behave exactly as today.
- `normalise_deny_entry` must accept `*` and still reject `?`, `#` and
  whitespace. A pasted config must not change meaning silently.
- `--audit` candidates stay literal (I6 round trip). Optionally, suggest a
  wildcard form when the same surface repeats under different owners.
- `DEFAULT_DENY` could then cover generic private surfaces such as
  `github.com/*/*/settings`. That follows the OQ-4 rule (generic, not drawn
  from the user's history), but adding entries is a separate decision.
