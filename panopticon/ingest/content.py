"""Content store for extracted article content.

Layout::

  ~/.local/state/behaviour/content/
    articles.jsonl           — index (one JSON object per line)
    <sha256[:2]>/
      <sha256>.json          — raw extraction (Readability or Trafilatura output)
      <sha256>.md            — Markdown conversion

The index maps content hashes to metadata. Content is de-duplicated by
content hash; re-extractions of the same URL with a different hash
produce new entries.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from panopticon.store import state_dir

_CONTENT_DIR = "content"
_INDEX = "articles.jsonl"
_MIN_TEXT_LENGTH = 500
_MIN_QUALITY = 0.0  # everything stored; quality is metadata


def content_dir(root: Path | str | None = None) -> Path:
    root = Path(root) if root else state_dir()
    return root / _CONTENT_DIR


def content_hash(text: str) -> str:
    """SHA-256 hex digest of *text* (used for de-duplication)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def quality_score(
    *,
    text_content: str,
    title: str | None = None,
    content_html: str | None = None,
) -> float:
    """Score extraction quality 0.0–1.0.

    Penalises short content, missing titles, and low text/link ratios.
    Consumers should treat scores < 0.3 as likely junk.
    """
    score = 1.0

    text_len = len(text_content)
    if text_len < 100:
        return 0.0
    if text_len < _MIN_TEXT_LENGTH:
        score -= 0.3
    if text_len < 200:
        score -= 0.3

    if not title or not title.strip():
        score -= 0.3

    if content_html:
        try:
            score = _penalise_low_text_link_ratio(score, content_html, text_len)
        except Exception:
            pass

    lines = [ln.strip() for ln in text_content.splitlines() if ln.strip()]
    if lines:
        # Penalise content that looks like a nav / list of links.
        short_line_ratio = sum(1 for ln in lines if len(ln) < 40) / len(lines)
        if short_line_ratio > 0.8:
            score -= 0.3

    return max(0.0, min(1.0, score))


def _penalise_low_text_link_ratio(
    score: float, html: str, text_len: int
) -> float:
    """Reduce score if the text/link ratio suggests a link farm."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    link_text = "".join(tree.xpath("//a//text()"))
    link_len = len(link_text.strip()) if link_text else 0
    if text_len > 0 and link_len / text_len > 0.5:
        return score - 0.3
    return score


@dataclass
class ContentStore:
    """Per-domain content storage with de-duplication and quality scoring.

    Thread-safe only for writes from a single process (the native
    messaging host is single-threaded); reads are lock-free because
    JSONL appends are atomic.
    """

    root: Path
    domain: str

    def store(
        self,
        *,
        url: str,
        title: str | None,
        text_content: str,
        content_html: str,
        byline: str | None = None,
        excerpt: str | None = None,
        site_name: str | None = None,
        published_time: str | None = None,
        captured_at: str | None = None,
        extractor: str = "readability",
    ) -> dict[str, Any] | None:
        """Store extracted content and return the index entry.

        Returns ``None`` if already stored with the same content hash.
        """
        ch = content_hash(text_content)
        index_path = self.root / _INDEX
        index_path.parent.mkdir(parents=True, exist_ok=True)

        quality = quality_score(
            text_content=text_content,
            title=title,
            content_html=content_html,
        )

        # Write content files.
        shard = ch[:2]
        shard_dir = self.root / shard
        shard_dir.mkdir(parents=True, exist_ok=True)

        raw = {
            "content_hash": ch,
            "url": url,
            "domain": self.domain,
            "title": title,
            "byline": byline,
            "excerpt": excerpt,
            "site_name": site_name,
            "published_time": published_time,
            "text_content": text_content,
            "content_html": content_html,
            "length": len(text_content),
            "captured_at": captured_at or datetime.now(UTC).astimezone().isoformat(),
            "extractor": extractor,
            "quality_score": round(quality, 3),
        }
        json_path = shard_dir / f"{ch}.json"
        _atomic_write_text(json_path, json.dumps(raw, separators=(",", ":"), ensure_ascii=False))

        # Convert HTML to Markdown.
        md = _html_to_markdown(content_html, url)
        md_path = shard_dir / f"{ch}.md"
        frontmatter = _render_frontmatter(raw)
        _atomic_write_text(md_path, frontmatter + "\n" + md)

        # Check de-duplication: same hash → skip.
        if _index_has_hash(index_path, ch):
            return None

        entry = {
            "content_hash": ch,
            "url": url,
            "domain": self.domain,
            "title": title,
            "extractor": extractor,
            "captured_at": captured_at or datetime.now(UTC).astimezone().isoformat(),
            "quality_score": round(quality, 3),
        }
        _append_index(index_path, entry)
        return entry

    def has_content(self, ch: str) -> bool:
        return (self.root / ch[:2] / f"{ch}.json").exists()

    def list_articles(self) -> list[dict[str, Any]]:
        """Return all index entries."""
        return _read_index(self.root / _INDEX)


def _html_to_markdown(html: str, base_url: str | None = None) -> str:
    """Convert extracted article HTML to Markdown using markdownify."""
    from markdownify import markdownify

    return markdownify(
        html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "noscript"],
    )


def _render_frontmatter(raw: dict[str, Any]) -> str:
    """Render YAML frontmatter for a Markdown file."""
    lines = [
        "---",
        f"url: {raw.get('url', '')}",
        f"domain: {raw.get('domain', '')}",
        f"title: {raw.get('title', '') or ''}",
        f"site: {raw.get('site_name', '') or ''}",
        f"byline: {raw.get('byline', '') or ''}",
        f"captured_at: {raw.get('captured_at', '')}",
        f"content_hash: {raw.get('content_hash', '')}",
        f"extractor: {raw.get('extractor', '')}",
        f"quality_score: {raw.get('quality_score', '')}",
        "---",
    ]
    return "\n".join(lines)


def _append_index(path: Path, entry: dict[str, Any]) -> None:
    line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def _index_has_hash(path: Path, ch: str) -> bool:
    """Check whether the index already has an entry for *ch*."""
    if not path.exists():
        return False
    # Short-circuit: scan the index for the hash.
    target = f'"content_hash":"{ch}"'
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if target in line:
                return True
    return False


def _read_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
