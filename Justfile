# Justfile — panopticon dev tasks. Run `just` to list.

ext := "firefox-extension"

check: lint test

# List recipes.
default:
    @just --list

# Run the test suite.
test:
    uv run --extra dev pytest -q

# Lint.
lint:
    uv run --extra dev ruff check .

# Needs WEB_EXT_API_KEY and WEB_EXT_API_SECRET (JWT issuer/secret from
# https://addons.mozilla.org/developers/addon/api/key/). Bump the manifest
# version first: AMO rejects a version it has already seen.
# Sign the extension via the AMO API (unlisted) → web-ext-artifacts/*.xpi.
sign-extension:
    @test -n "${WEB_EXT_API_KEY:-}" -a -n "${WEB_EXT_API_SECRET:-}" || { echo "set WEB_EXT_API_KEY and WEB_EXT_API_SECRET" >&2; exit 1; }
    web-ext sign --source-dir {{ext}} --channel unlisted

install-manifest:
    panopticon-firefox-host install-manifest

alias sign := sign-extension
