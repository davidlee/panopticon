# panopticon privacy

What panopticon captures, where the boundaries are.

## Sway watcher

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

- the URL `scheme://host/path` of the active tab (query and fragment
  stripped before emission)
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
`focus_segment` to discount in-browser dwell that happened while Sway
was focused on another application.

## Future producers

- Shell commands / cwd: from zsh `preexec` / `precmd` hooks.

No producer should rely on title-scraping for content it can capture
properly at the source.
