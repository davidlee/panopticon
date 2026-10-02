# Notes SL-008: digest: privacy-surface flag for gate audit

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

Evidence here is counts only (design I4): no real host, URL, title or SHA of
a private page is recorded.

## PHASE-01 / PHASE-02 (2026-10-02)

- `doctrine slice phases` reported "up to date" without creating the PHASE-01
  sheet (02 and 03 were created). Hand-made from the 02 template. A doctrine
  bug, not a project issue.
- `gate._normalise_path` became public `normalise_path`; the audit takes the
  candidate's first segment from it.
- A directory-wide `ruff format` again rewrote ~25 unrelated files (as in
  SL-007). Restored from HEAD before commit. Format named files only.
- `config.py` and `select.py` were already unformatted at HEAD; left alone.

## PHASE-03 VH (2026-10-02, `openai/gpt-4.1-mini`, prompt v4)

- **Migration.** The 3 v3 records were deleted. A `--limit 3` run picks the
  *newest* pending pages, so it digested 3 new pages instead (all `public`);
  the original 3 stay pending for the backfill. Lesson: deleting records and
  running `--limit N` does not re-digest those records.
- **VH-1 (R3).** The original 3 pages were sent directly through
  `build_request` + the real transport (no store write): all `public`;
  summaries comparable in length and accuracy to v3; entities 10/9/10 → 10/8/10.
- **VH-2 (recall).** 4 synthetic `*.example` positives: 4/4 flagged as
  non-public, 2/4 with the expected reason. The inbox came back
  `personal_record` and the order history `account`. The audit acts on
  non-public versus public, so reason confusion only affects the label.
- **VH-3 (canary).** `--limit 20`: 20 digested, 0 failures. All 23 records
  `public`, so the audit lists nothing (`public=23`). Hosts were spot-checked
  by the user's agent in the terminal: all public sites.
- Config at `~/.config/panopticon/digest.toml` (outside the repo):
  `enabled = true` from this phase.

## Backfill (after close, 2026-10-02)

- 8 chunks of ≤200 pages, about 1.4k digested in total; 0 failure markers,
  0 provider failures.
- `--audit` after the backfill: 7 records flagged (6 `account`,
  1 `private_message`), all genuine private surfaces on review, 0 false
  positives seen. One `private_message` was really a personal record (the
  VH-2 reason confusion again).
- 6 deny entries added to the user's config (widened from the audit's
  candidates by hand where the whole host is private); re-audit:
  `covered=7`. None went into `DEFAULT_DENY` (user: config only).
- Per-repo settings paths (`/<owner>/<repo>/settings`) cannot be expressed
  as a deny prefix; each needs its own entry.
