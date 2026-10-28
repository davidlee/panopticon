# Panopticon

A local record of what I have been doing and reading, so
[SATAN](https://github.com/davidlee/SATAN) has something concrete to notice:
which applications held my attention, which pages I spent time on, what those
pages said, and what I committed to my projects.

Panopticon captures desktop and Firefox activity, stores readable page
content, and derives attention spans and daily summaries. SATAN reads those
files through its tools; it supplies the interpretation and conversation.
Panopticon runs independently of SATAN and Emacs.

![eyes](./panopticon.jpg)

Capture stays local under `$XDG_STATE_HOME/behaviour/` (default
`~/.local/state/behaviour/`). The optional `panopticon-digest` batch job can
send selected page text to an LLM provider for summaries. It is disabled by
default and has its own local gate, configuration and timer.

## What it sees

| Source | Captured information | What it gives SATAN |
|---|---|---|
| Desktop: Sway, Niri or Umbriel | Window focus, application, title, workspace and output, through compositor IPC | Current focus and time spent in applications |
| Firefox attention | Active tabs, redacted URLs, titles, navigation, browser focus and idle signals | Recent browser attention and time by domain |
| Firefox page content | Mozilla Readability extraction after 30 seconds of dwell or an explicit right-click action | Searchable text of pages I visited |
| Keyboard and pointer activity | Per minute: key presses (not modifiers or autorepeat), seconds with typing, seconds with pointer activity; keys per focused window (app and title). Read from evdev, so any compositor. A live rate on a local socket | Typing versus reading versus idle; typing rate per app and window; a rate for a status bar |
| Local Git repositories | Commits across local branches under `~/dev/*`, polled from the host | Project activity, including commits made inside jails |
| Optional page digest | Summary, claims, entities and an advisory privacy classification | A compact account of captured reading |

These are activity signals, not proof of reading or understanding. Desktop
focus and browser attention are derived separately; the segmentizer does not
currently intersect browser spans with compositor focus spans.

## How it fits together

```text
 Sway / Niri / Umbriel
          │
 panopticon-desktop ──┬──▶ raw/desktop-*
                     └──▶ current/desktop.json

 Firefox extension (attention + Readability)
          │
 panopticon-firefox-host ──┬──▶ raw/firefox-*
                          └──▶ content/ (JSON + Markdown)

 raw/ ──▶ panopticon-segmentize ──┬──▶ segments/focus-* + browser-*
                                 └──▶ histograms/daily-*

 local Git repos ──▶ panopticon-git ──▶ segments/git-*

 content/ ──▶ panopticon-digest (optional)
                 local gate → LLM provider ──▶ digest/

 SATAN reads activity, content and digests from these local files.
```

The desktop watcher reconnects with exponential backoff. Its adapters emit
one normalized `desktop` stream, retaining `producer` to distinguish the
compositor. Auto-detection probes live sockets in the order Niri, Sway,
Umbriel; `--compositor` overrides it. The executable `panopticon-sway` remains
a Sway wrapper, and the deployed desktop service retains the name
`panopticon-sway`.

The Firefox extension sends events through native messaging. The host
re-validates and redacts them, appends attention events to `raw/`, and routes
extracted page bodies straight to `content/`. It does not fetch pages: content
comes from the page already open in Firefox.

### How SATAN uses it

SATAN's Emacs tools provide read-only views:

- **`activity_read`** exposes today's histogram, recent focus and browser
  segments, and current desktop focus. Its current-focus reader replays the
  raw desktop stream.
- **`content_read`** lists recent captures, filters by domain or URL, searches
  the Markdown projection, reads page text in chunks, and retrieves digests.
  Recent, filter and search results include a digest summary when available.
- Git segments feed SATAN's Git-activity perception; `vcs_log` can inspect a
  repository when it needs more detail.

The file boundary keeps capture independent of the agent harness. Malebolge
currently reaches these SATAN tools through `satan-mcp` in Emacs. A consumer
may pass retrieved data to its own model; that is separate from Panopticon's
capture and digest boundaries.

### Freshness

Raw desktop and browser events are written as they arrive; extracted content
is available as soon as the native host stores it. Focus and browser segments
and their histograms update when `panopticon-segmentize` runs. The shipped
timer runs nightly at 03:30 with a randomized delay; run it manually for a
same-day refresh. A stored histogram is therefore not a live view of today.

`panopticon-git` writes directly to `segments/`, so a deployment polling every
five minutes exposes commits without waiting for the nightly batch. Each poll
scans local branches over a seven-day horizon by default and skips commits
already present in the relevant day file. It needs no Git hook, fetch or push.

## Storage and retention

```text
~/.local/state/behaviour/
├── raw/
│   ├── desktop-YYYY-MM-DD.jsonl
│   ├── firefox-YYYY-MM-DD.jsonl
│   └── keyrate-YYYY-MM-DD.jsonl
├── current/
│   └── desktop.json
├── segments/
│   ├── focus-YYYY-MM-DD.jsonl
│   ├── browser-YYYY-MM-DD.jsonl
│   └── git-YYYY-MM-DD.jsonl
├── histograms/
│   └── daily-YYYY-MM-DD.json
├── content/
│   ├── articles.jsonl
│   └── <hash[:2]>/
│       ├── <hash>.json
│       └── <hash>.md
└── digest/
    └── <hash[:2]>/
        ├── <hash>.digest.json
        └── <hash>.digest.fail.json
```

| Tier | Retention |
|---|---|
| Raw events | Seven days; deletion requires a matching derived segment file |
| Keyrate minutes (`raw/keyrate-*`) | Kept indefinitely: no segment is derived from them yet, so raw retention leaves them |
| Segments, including Git | 90 days |
| Daily histograms | Kept indefinitely |
| Extracted content and digests | No automatic retention yet |

Retention runs with the segmentizer. Raw events use append-only JSONL writes;
current state, derived segments and histograms are replaced atomically.

Content is keyed by SHA-256 of extracted text. Identical text shares an index
entry; changed text can produce a new hash even at the same URL. Each capture
stores extraction JSON, a Markdown projection and metadata including a quality
score. That score describes extraction quality, not whether a page is safe to
send to a model.

Desktop and Firefox attention events use the versioned schema, for example:

```json
{"v":1,"ts":"2026-10-19T09:15:03.412+11:00","source":"desktop","producer":"umbriel","event":"window_focus","window_id":42,"app_id":"firefox","workspace":"3"}
```

Git segments are a separate, flat format compatible with SATAN's original
hook: repository, remote, commit, subject, author, changed-file count and
timestamps. They are not schema-v1 events.

## Privacy boundaries

- No keystrokes, clipboard, screenshots or terminal output are captured.
  `panopticon-keyrate` counts key presses per minute; it never records which
  key, nor when any single press happened.
- Desktop and browser titles are stored verbatim and may contain sensitive
  text or paths. URL filtering does not sanitize titles or extracted bodies.
- Firefox URLs retain the host and path. Queries and fragments are stripped,
  except identity parameters such as Hacker News `id` and YouTube `v`.
- Private Firefox tabs/windows and sensitive URL schemes are excluded by the
  extension; the host also validates incoming events and re-applies URL
  redaction. `file:` URLs are disabled by default.
- **Page bodies are captured.** Readability runs on a cloned DOM after dwell
  or explicit extraction; the host stores the extracted HTML and text locally.
  The digest denylist governs outbound summarization, not local capture.
- Capture, segmentation and Git polling make no network calls. The optional
  digest job is the runtime pipeline's only network egress.

The [schema reference](docs/schema.md), [privacy notes](docs/privacy.md) and
[extension README](firefox-extension/README.md) contain further detail and
installation instructions. Their older statements that Firefox never captures
page bodies predate content extraction; the content path described here is
implemented.

## Run it

You need Linux with Sway, Niri or Umbriel for desktop capture, and Firefox with
the extension for browser capture. The Python package requires Python 3.12+.

```sh
# Nix package (all seven entrypoints)
nix build .#panopticon

# Or install into a local virtual environment
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
```

### Desktop and Firefox

```sh
panopticon-desktop -vv
# Or select explicitly:
# panopticon-desktop --compositor umbriel -vv

# Install the Firefox native-messaging manifest
panopticon-firefox-host install-manifest
```

The watcher is a foreground daemon. Firefox starts its native host through
the installed manifest; do not run the host interactively. Load
`firefox-extension/manifest.json` through `about:debugging` for a temporary
add-on. For permanent installation, see the extension README's signing steps
(`just sign-extension` / `just fetch-extension`).

```sh
# Inspect capture locally
tail -f ~/.local/state/behaviour/raw/desktop-$(date +%F).jsonl
tail -f ~/.local/state/behaviour/content/articles.jsonl

# Refresh derived activity and poll Git once
panopticon-segmentize -v
panopticon-git -v

jq '.per_app_seconds, .per_domain_seconds' \
  ~/.local/state/behaviour/histograms/daily-$(date +%F).json
```

These commands use the default state path; adjust it if `XDG_STATE_HOME` is
set. Use `--help` for per-command root overrides and logging options.

### Keyboard and pointer rate

```sh
panopticon-keyrate -v
# Live rate, one JSON line a second — e.g. for a bar:
socat -u UNIX-CONNECT:$XDG_RUNTIME_DIR/panopticon/keyrate.sock -
```

It reads `/dev/input`, so the user must be in the `input` group (RSK-002).
Until SATAN reads `raw/keyrate-*`, it also writes the retired wpm-daemon's TSV
to `$XDG_STATE_HOME/satan/log/wpm/` (`--no-legacy` to stop; IMP-005).

### Page digest (opt-in egress)

`panopticon-digest` is a separate batch job, disabled unless its config enables
it. The local gate rejects built-in and user-denied domains or path prefixes,
local/intranet hosts, low-quality extractions and short text. An optional
allowlist only narrows the selection. The latest capture per URL is considered;
already completed hashes are skipped.

Create `$XDG_CONFIG_HOME/panopticon/digest.toml` (default
`~/.config/panopticon/digest.toml`). Unknown keys are errors:

```toml
enabled = true
max_pages_per_run = 50

[gate]
deny = ["mybank.example", "github.com/my-employer"]
# allow = ["lwn.net"]
min_chars = 1500
min_quality = 0.7

[digest]
endpoint = "https://openrouter.ai/api/v1/chat/completions"
model = "<provider/model>"   # required; must support strict json_schema
# The key comes from one of these; set at most one.
api_key_env = "OPENROUTER_API_KEY"
# api_key_file = "~/.config/llm-gateway/keys/<client>"
max_input_chars = 24000
max_output_tokens = 1500
```

The key comes from the named environment variable or key file; set at most one.
A literal key in config is refused. For a local gateway, set `endpoint =
"http://127.0.0.1:4000/v1/chat/completions"` and `api_key_file =
"~/.config/llm-gateway/keys/<client>"`. Through the gateway the model is the
gateway's name, `<gateway provider>/<upstream id>` (for example
`openrouter/openai/gpt-4.1-mini`). `http` is accepted only to a loopback
IP literal (not `localhost`); elsewhere use `https`.

For a passing page, page-derived input is the host, title and text,
truncated to `max_input_chars`. The page URL and HTML are not separate payload
fields; extracted text can itself contain sensitive information or URLs.

Preview before a live run:

```sh
panopticon-digest --dry-run       # ignores enabled/key; no network or writes
panopticon-digest --limit 3 -v    # small live run; requires enabled + key
```

Each record holds `summary`, `claims[]`, `entities[]` and `private_surface`.
Entity types use a closed vocabulary: person, organisation, place, software,
hardware, work, concept, event or other. Content failures receive a marker so
the same hash is not repeatedly submitted.

`private_surface` is the model's advisory classification: public, draft,
private_message, account, personal_record or other_private. It arrives after
sending and cannot prevent that send. Use it to inspect gaps in the gate:

```sh
panopticon-digest --audit
```

The audit reads stored records and config, makes no network calls, and writes
nothing. It reports flagged pages the current gate would still send and
suggests deny entries. Its output contains paths and titles; keep that manual
output out of the service journal and version control. Digests and captured
pages are untrusted source material for consumers, never instructions.

To schedule digests, wire the service and timer through Home Manager or a Nix
flake, or install `systemd/digest.{service,timer}` as user units. With
`api_key_file` the unit needs no environment file. With `api_key_env`, a Home
Manager or flake unit must supply the variable itself (for example an
`Environment=` or `EnvironmentFile=` directive); only the shipped reference
unit reads the fixed path `~/.config/panopticon/digest.env` when present, for
example `OPENROUTER_API_KEY=…`. Restrict whichever file holds the key to mode
`0600`. Then enable `digest.timer`. The shipped units do not enable themselves.

## Development and deployment

```sh
just check                          # Ruff lint + pytest
nix build .#panopticon --no-link     # package/build check
```

Most implementation is Python; the Firefox producer is JavaScript with
vendored Mozilla Readability. Compositor adapters normalize native IPC into a
shared desktop model. Add a raw producer through `RawStore`, a derivation in
the segmentizer's `_SOURCES` table, and the corresponding retention mapping.

Home Manager deployment pins the package in `~/flakes`. Editing this checkout
alone does not update running services. `./bin/reload-hm` updates that flake
input and runs `home-manager switch`; it is a deployment action, not a dev
check. Override its targets with `PANOPTICON_FLAKES_DIR` and
`PANOPTICON_HM_TARGET`.

## Remaining work

Shell/terminal producers and a dedicated Emacs or idle/lock watcher are future
work; Firefox already supplies its own idle signals. Bookmark backfill and
capture are proposed (IDE-001), not implemented. Automatic content retention
(RSK-001), host-side capture/redaction configuration (IDE-003), and wildcard
path segments in digest deny entries (IDE-005) also remain open. Current deny
paths are literal prefixes, not glob patterns. The keyrate cutover (SATAN
reads the raw stream; the legacy TSV goes) is IMP-005, and `input` group
membership is RSK-002.

## License

Private / not yet licensed.
