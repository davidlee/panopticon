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

## Future producers

- Browser URLs: from a dedicated firefox extension + native host.
- Shell commands / cwd: from zsh `preexec` / `precmd` hooks.

No producer should rely on title-scraping for content it can capture
properly at the source.
