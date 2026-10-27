# CHR-003: Align version skew: pyproject.toml 0.1.0 to flake.nix 0.2.1 (SL-004 §6 deferral)

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

## Resolution (2026-10-27)

`pyproject.toml` is the single source (0.3.0). `flake.nix` reads it via
`builtins.fromTOML`; `panopticon.__version__` reads installed metadata.
`tests/test_smoke.py` guards both. `Cargo.toml` (0.1.0) versions a separate
Rust crate and is left alone.
