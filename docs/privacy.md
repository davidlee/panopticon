# panopticon privacy

What panopticon captures, where the boundaries are.

## Desktop watcher

Covers the compositor metadata captured by `panopticon-desktop` on either
supported compositor — Sway and Niri alike.

Captures (compositor metadata only):

- focused window `app_id` / X11 `class` / `pid`
- window title (verbatim)
- workspace + output names
- focus / title-change / new / close timestamps

Does **not** capture:

- keystrokes
- clipboard contents
- screenshots / framebuffers
- terminal output
- browser page contents (URLs, form data)

Window titles can include URLs (browser tabs) and file paths (editors).
Redaction policy lives downstream:

1. **Producer-level** allow/deny lists drop titles for selected
   `app_id`s (e.g. password managers, banking apps).
2. **Segmentizer-level** regex redaction rewrites titles when
   materializing segments.
3. **Consumer-level** aggregation (`agg=app_histogram`) omits titles
   entirely.

## Firefox extension + native host

Captures:

- the URL `scheme://host/path` of the active tab (fragment and query
  stripped before emission, except a short per-host list of params that
  identify the page — `news.ycombinator.com` `id`, YouTube `v`; search
  terms and every other param are still stripped)
- domain (lowercased)
- tab title (verbatim, same caveats as sway window titles)
- window id, tab id, audible / muted / pinned flags
- navigation transition type for committed navigations
- system idle state from `idle.onStateChanged`

Does **not** capture:

- page bodies, form contents, typed input, password fields
- cookies, headers, request/response bodies
- full browsing history (no `history.search` calls)
- screenshots or DOM scraping
- private (incognito) windows or tabs
- `about:`, `moz-extension:`, `chrome:`, `resource:`, `view-source:`,
  `data:`, `blob:`, `javascript:`, or (by default) `file:` URLs

Redaction is applied twice — once in the extension, once in the host —
so a buggy or hostile extension cannot bypass the policy by skipping its
own filter. The host always re-stamps `source="firefox"`; the extension
cannot lie about provenance.

The downstream segmentizer joins `browser_tab_segment` against
`focus_segment` to discount in-browser dwell that happened while the
compositor was focused on another application.

## Page digest: the only egress

Capture never touches the network. No producer, the native host, the
segmentizer or the git poller makes a network call. `panopticon-digest` is the
sole network egress (DEC-002): a separate, opt-in binary with its own unit and
timer, shipped disabled. It does nothing without a config file and
`enabled = true`; `--dry-run` never makes a network call and never writes.

Before anything is sent, a local, deterministic gate decides per page. A
model never decides whether text may reach a model. A page is held back if:

- its URL does not parse, its scheme is not `http`/`https`, or it has no host;
- its host is local: an IP literal, a single-label name, `localhost`, or under
  `.local`, `.lan`, `.internal` or `.home.arpa`;
- it matches a deny entry: the built-in list (mail, banking and payments,
  chat, AI chat, office suites and file stores, auth and password managers,
  search engines, Australian government services, plus private paths on
  public hosts such as messages, account settings and checkout) plus the
  user's `deny` list. An entry is a host, matching it and its subdomains, or
  a host with a path prefix (`github.com/my-employer`), matching only under
  that path;
- an `allow` list is set and the host is not on, or under, an entry (allow
  only narrows; it never overrides a deny entry);
- its extraction quality is below `min_quality`, or its text is shorter than
  `min_chars`.

For a page that passes, exactly three things are sent to the configured
endpoint, and nothing else:

1. the host (lowercased, from the stored URL);
2. the page title;
3. the extracted text (`text_content`), truncated to `max_input_chars`.

Never sent: the URL path or query, the page's links, capture timestamps,
other pages, or any desktop or browser attention data.

The provider is the user's choice; the endpoint must be `https`. The API key
is read only from an environment variable, never from the config file. The
client refuses redirects (so neither the key nor the page reaches another
host), ignores `*_PROXY` variables and verifies certificates. Logs carry only
the content hash, HTTP status and failure kind: never page text, request
bodies, headers or credentials.

Results are stored locally under `digest/`, keyed by content hash, so an
unchanged page is sent at most once. Digests are model output about
third-party pages: consumers must treat them as untrusted data, never as
instructions.

## Future producers

- Shell commands / cwd: from zsh `preexec` / `precmd` hooks.

No producer should rely on title-scraping for content it can capture
properly at the source.
