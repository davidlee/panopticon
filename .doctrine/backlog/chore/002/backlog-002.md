# CHR-002: flake devshell omits pytest-asyncio; async suite unrunnable in bare jail

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

## Problem

The flake **devshell** (`flake.nix:50`, `python3.withPackages`) provides only
`pytest`, not `pytest-asyncio`. The `buildPythonApplication` checkPhase
(`flake.nix:39`) does list it, but `nix` is unavailable inside the build jail,
so `nix flake check` cannot run there. Net effect: a bare `python3 -m pytest` in
the jail reports **10 false failures** — every `async def test_` in
`tests/test_compositor_runner.py` and `tests/test_compositor_sway_session.py`
errors with "async def functions are not natively supported". The
`asyncio_mode = "auto"` setting in `pyproject.toml` is inert without the plugin.

## Impact

The behaviour-preservation gate (SL-002 suites green) is unverifiable with the
default in-jail runner; it looks red when it is not. Surfaced during SL-003
PHASE-01 execution.

## Workaround (in use)

`uv venv --system-site-packages` + `uv pip install pytest-asyncio`, then run
pytest from that venv → full suite **291 passed / 3 skipped**.

## Fix

Add `pytest-asyncio` to the devshell package set (`flake.nix:50`) so the jail's
default `python3 -m pytest` runs the async suite. `flake.nix` is already dirty in
the working tree — fold this in there.
