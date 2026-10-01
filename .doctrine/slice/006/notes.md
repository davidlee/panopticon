# Notes SL-006: panopticon-digest: opt-in page digest over the content store

Durable per-slice scratchpad — tracked in git. The place to lift anything from a
disposable phase sheet (`.doctrine/state/.../phase-NN.md`) that must survive
`rm -rf` before the slice close-out audit harvests it.

## Design process (2026-10-01)

- Sliced from IDE-002; governed by DEC-002. Design locked after three adversarial
  rounds (fresh general-purpose subagents; the codex MCP was down). Findings and
  dispositions are in design §10.
- User decisions: D1 (gate + digest only), D2 (stdlib urllib), D3 (TOML + env
  secrets), D4 (deny-always, allow-narrows), D10 (delete extractor), D15 (move
  amo.py to tools/).
- Corpus facts in design §2 are aggregates only. Keep it that way: never commit
  URLs or titles from the user's content store.
- A pre-existing lint failure (unsorted imports, tests/test_git_poller.py) was
  fixed separately in 4120613.
- IDE-002's body still lists ISS-003 as open, but ISS-003 is resolved
  (899b6b8). Left unedited.
- Model choice (OQ-1) is pending web-agent research on providers; only PHASE-04
  needs it.

## PHASE-01 groundwork (2026-10-01)

- `panopticon/fsutil.py` is the single atomic-write / flock implementation.
  Four atomic-write copies migrated, not three: `firefox_host/install.py` was
  missed by design §2. `exclusive_lock` does not mkdir; callers own directories.
- `panopticon/settings.py`: `config_dir()`, `load_toml()`. `load_toml` raises
  `OSError` / `TOMLDecodeError`; the digest shell decides "no config → exit 0"
  by checking existence first.
- `tools/amo.py` (dev tool, outside the wheel); pytest `pythonpath = ["."]`.
- I2 tripwire: `tests/test_network_boundary.py`. It whitelists
  `panopticon/digest/client.py` by path; third-party libraries are not covered
  (trafilatura would have evaded it — removed anyway).
- `uv lock` works in the jail. The repo is not ruff-formatted and `just check`
  has no format gate; format new files only.
