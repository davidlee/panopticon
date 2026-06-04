# Justfile — panopticon dev tasks. Run `just` to list.

ext := "firefox-extension"
zip := "panopticon.zip"

check: lint test

# List recipes.
default:
    @just --list

# Run the test suite.
test:
    uv run pytest -q

# Lint.
lint:
    uv run ruff check .

# Package the Firefox extension into panopticon.zip for upload (AMO) / signing.
# manifest.json must sit at the archive root, so we zip from inside the
# extension dir. Dotfiles (.DS_Store, editor swap files) are excluded.
package-extension:
    test -f {{ext}}/manifest.json
    rm -f {{zip}}
    cd {{ext}} && zip -r -X -q ../{{zip}} . -x '.*' '*/.*'
    @echo "built {{zip}}:"
    unzip -l {{zip}}

install-manifest:
    panopticon-firefox-host install-manifest

alias package := package-extension
