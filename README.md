# panopticon

Local desktop-behaviour capture for Linux (Sway). Producers emit
normalized JSONL events; a batch segmentizer derives attention spans
and daily histograms. Consumers (e.g.
[SATAN](https://github.com/davidlee/emacs-config/tree/main/satan)) read the derived
data for aggregation, search, and self-reflection on digital habits.

Everything stays on disk at `~/.local/state/behaviour/`. Nothing
leaves the machine.

## Architecture

```
 sway ipc            firefox extension          (future: ghostty,
 ─────────┐          ──────────────┐             emacs, idle)
          │                        │                   │
   panopticon-sway    panopticon-firefox-host          │
          │                        │                   │
          └──────────┬─────────────┴───────────────────┘
                     ▼
          raw/  (per-source, per-day JSONL)
                     │
          panopticon-segmentize  (nightly batch)
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
     segments/   histograms/  current/
     (90 d)      (forever)    (atomic snapshot)

   firefox extension (right-click or 30 s dwell)
          │
   Readability.js  (in-browser DOM extraction)
          │
   panopticon-firefox-host
          │
          ▼
     content/  (articles.jsonl + markdown)
     (no retention yet — follow up)
```

## Components

| Binary | What it does |
|--------|-------------|
| `panopticon-sway` | Sway IPC watcher daemon. Tracks window focus, titles, workspaces. Reconnects with exponential backoff. |
| `panopticon-firefox-host` | Native messaging host for the Firefox WebExtension. Receives browser attention events, re-validates and writes JSONL. Routes content extraction to the content store. |
| `panopticon-segmentize` | Nightly batch. Derives `focus_segment` and `browser_tab_segment` events, computes daily histograms, enforces retention. |
| `panopticon-git` | Host-side git-commit poller (5-min timer). Scans `~/dev/*`, appends one segment per new commit straight to `segments/git-YYYY-MM-DD.jsonl`. Byte-compatible with the SATAN `post-commit` hook, but env-agnostic so it also captures commits made inside bwrap jails (where the hook never fires). |

The Firefox WebExtension lives in `firefox-extension/`. See its
[README](firefox-extension/README.md) for install instructions.

Planned producers: ghostty/zsh shell hook, emacs, idle/lock watcher.

## Storage layout

```
~/.local/state/behaviour/
├── raw/
│   ├── sway-YYYY-MM-DD.jsonl         7-day TTL (only after segmented)
│   └── firefox-YYYY-MM-DD.jsonl      7-day TTL (only after segmented)
├── segments/
│   ├── focus-YYYY-MM-DD.jsonl        90-day TTL
│   ├── browser-YYYY-MM-DD.jsonl      90-day TTL
│   └── git-YYYY-MM-DD.jsonl          90-day TTL (written direct, see below)
├── histograms/
│   └── daily-YYYY-MM-DD.json         kept forever
├── current/
│   └── sway.json                     last-known compositor state
└── content/
    ├── articles.jsonl                index: one JSON object per extracted article
    └── <hash[:2]>/
        ├── <hash>.json               raw Readability / Trafilatura output
        └── <hash>.md                 Markdown with YAML frontmatter

**content/ is not yet retention-managed** — the index and article
files accumulate indefinitely. Retention is tracked as follow-up work.
```

Writes use POSIX `O_APPEND` — line-atomic up to `PIPE_BUF` (4 KiB on
Linux), so concurrent producers need no coordination. Retention is
source-aware: raw files are deleted only after matching segments exist.

**Git is the freshness exception.** `panopticon-git` writes directly to
`segments/` (not through `raw/ → segmentize`) so commits surface within a
poll interval rather than next-day. Its line is a flat, hook-compatible
object — `{repo, slug, remote, sha, subject, author, files_changed,
start_ts, end_ts}` — not a schema-v1 `Event`. Dedup is stateless: each
poll re-enumerates `git log --branches --since=7.days` and skips any
`(repo, sha)` already present in the day-file, so the segment files are
their own dedup state. During the transition the SATAN `post-commit` hook
may co-write the same sha; the `(repo, sha)` dedup absorbs it. Retiring
that hook is tracked in `.emacs.d` ISSUE-006 (step 2).

## Event schema

Every event is one JSON line:

```json
{"v": 1, "ts": "2026-05-27T09:15:03.412+10:00", "source": "sway", "event": "window_focus", ...}
```

See [`docs/schema.md`](docs/schema.md) for the full reference and
[`docs/privacy.md`](docs/privacy.md) for what is and isn't captured.

## Privacy

- No keystrokes, clipboard, or screenshots.
- URLs stripped to `scheme://host/path` (query + fragment removed).
- Incognito tabs and sensitive schemes (`about:`, `moz-extension:`,
  `data:`, etc.) dropped at both extension and host.
- Redaction applied twice (extension → host) so a buggy extension
  cannot bypass the policy.
- All data local. No network calls.

### Content extraction

The Firefox extension can extract the readable text of pages the user
dwells on (30 s auto-trigger) or via right-click → "Extract page
content for Panopticon". Extraction uses Mozilla Readability on a
cloned DOM; the extracted HTML is converted to Markdown locally.
Content is de-duplicated by SHA-256 hash — re-visiting a page does
not create a new entry. A quality score (0–1) is computed for each
extraction; consumers should treat scores below 0.3 as likely junk.

Page content is stored in ``~/.local/state/behaviour/content/``
alongside metadata (URL, title, domain, extractor, quality score).
The raw extraction JSON is kept to allow re-conversion later without
re-visiting the page.

## Quick start

### Install

```sh
# nix (recommended)
nix build .#panopticon

# or: local venv
uv venv && uv pip install -e ".[dev]"
```

### Run the sway watcher

```sh
panopticon-sway -vv
tail -f ~/.local/state/behaviour/raw/sway-$(date +%Y-%m-%d).jsonl
```

### Run the firefox pipeline

```sh
# install native messaging host manifest
panopticon-firefox-host install-manifest

# load extension in Firefox:
#   about:debugging → Load Temporary Add-on → firefox-extension/manifest.json

tail -f ~/.local/state/behaviour/raw/firefox-$(date +%Y-%m-%d).jsonl
```

### Content extraction

The Firefox extension extracts page content on 30 s dwell or right-click.
Two-stage design:

1. **Browser-side:** Mozilla Readability runs on a cloned DOM, produces
   cleaned article HTML + text.
2. **Local fallback:** Trafilatura fetches and extracts URLs not captured
   in-browser (batch backfill, non-browser sources).
   **Not yet wired —** the module is implemented and tested but has no
   CLI entrypoint or daemon; currently dead code.

Watch content flow in:

```sh
tail -f ~/.local/state/behaviour/content/articles.jsonl
```

For a specific article's Markdown:

```sh
# find the hash from articles.jsonl, then:
cat ~/.local/state/behaviour/content/<hash[:2]>/<hash>.md
```

### Run the segmentizer

```sh
panopticon-segmentize -v
jq '.per_app_seconds, .per_domain_seconds' \
  ~/.local/state/behaviour/histograms/daily-$(date +%Y-%m-%d).json
```

## Development

```sh
pytest              # 213 tests
ruff check .        # lint
nix build .#panopticon --no-link   # nix build sanity
```

### Propagating changes to systemd

The user units (`panopticon-sway.service`, `panopticon-segmentize.timer`)
are wired via home-manager, which pins to a nix flake lockfile. Source
edits don't reach running daemons until the lock is bumped:

```sh
./bin/reload-hm
```

This updates the flake lock in `~/flakes`, runs `home-manager switch`,
and clears any prior service failures. Override paths with
`PANOPTICON_FLAKES_DIR` and `PANOPTICON_HM_TARGET`.

## Adding a new producer

1. Write events matching the [schema](docs/schema.md) to
   `raw/<source>-YYYY-MM-DD.jsonl` via `panopticon.store.RawStore`.
2. Add a `derive_<source>_segments()` function in the segmentizer.
3. Add one row to the `_SOURCES` table in
   `panopticon/segmentizer/__main__.py`.

## License

Private / not yet licensed.
