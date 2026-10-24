"""Path of a captured page's Markdown, for handing to an agent (IMP-004).

`just content-path` prints the newest capture; `just content-path URL` the
newest capture of that page. "Newest" is the `.md` mtime, not index order:
re-sending an unchanged page rewrites its files but appends no index row.
The URL is redacted as the host redacts it, so a pasted URL matches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from panopticon.firefox_host.validate import redact_url
from panopticon.ingest.content import content_dir, read_index, shard_path


def find(root: Path, url: str | None = None) -> Path | None:
    """The newest `.md` under content ``root``, optionally for one page."""
    want = redact_url(url, record_file_urls=True) if url else None
    if url and want is None:
        return None
    paths = (
        shard_path(root, e["content_hash"], ".md")
        for e in read_index(root)
        if want is None or e.get("url") == want
    )
    return max((p for p in paths if p.exists()), key=lambda p: p.stat().st_mtime, default=None)


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="content-path",
        description="Print the Markdown path of a captured page.",
    )
    parser.add_argument("url", nargs="?", help="page URL (default: newest capture)")
    args = parser.parse_args(argv)

    path = find(root or content_dir(), args.url)
    if path is None:
        print(f"no capture{f' for {args.url}' if args.url else ''}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
