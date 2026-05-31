"""Trafilatura fallback extraction.

When a URL is not captured by the Firefox extension (e.g. batch
backfill, non-browser sources), this module fetches and extracts the
main text using Trafilatura.

Pure where possible; IO happens at the top-level ``extract`` function.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("panopticon.ingest.extractor")


@dataclass(frozen=True, slots=True)
class ExtractedArticle:
    url: str
    domain: str | None = None
    title: str | None = None
    text_content: str = ""
    content_html: str | None = None
    byline: str | None = None
    excerpt: str | None = None
    site_name: str | None = None
    published_time: str | None = None
    extractor: str = "trafilatura"


def extract(
    url: str,
    *,
    timeout: int = 30,
    user_agent: str | None = None,
) -> ExtractedArticle | None:
    """Fetch *url* and extract main text with Trafilatura.

    Returns ``None`` on fetch failure, empty extraction, or non-HTML
    response.
    """
    import trafilatura
    from courlan import validate_url
    from trafilatura.spider import focused_crawler

    if not validate_url(url):
        log.debug("trafilatura: invalid URL %s", url)
        return None

    try:
        downloaded = focused_crawler(
            url,
            max_redirects=3,
            timeout=timeout,
            user_agent=user_agent,
        )
    except Exception:
        log.debug("trafilatura: fetch failed for %s", url, exc_info=True)
        return None

    if downloaded is None:
        log.debug("trafilatura: fetch returned None for %s", url)
        return None

    extracted = trafilatura.bare_extraction(
        downloaded,
        output_format="python",
        url=url,
    )
    if extracted is None:
        log.debug("trafilatura: bare_extraction returned None for %s", url)
        return None

    raw_text = extracted.get("raw_text") or extracted.get("text") or ""
    if not raw_text.strip():
        return None

    # Extract content as cleaned HTML, then convert downstream.
    content_html = _to_html(extracted)

    domain = _domain_of(url)

    return ExtractedArticle(
        url=url,
        domain=domain,
        title=extracted.get("title"),
        text_content=raw_text,
        content_html=content_html,
        byline=extracted.get("author"),
        excerpt=_first_sentence(raw_text),
        site_name=extracted.get("sitename"),
        published_time=extracted.get("date"),
    )


def _to_html(extracted: dict[str, Any]) -> str | None:
    """Build a minimal HTML representation from Trafilatura output."""
    import lxml.html

    title = extracted.get("title")
    body = extracted.get("body") or extracted.get("raw_text") or ""
    if not body.strip() and not title:
        return None

    parts = ["<html><body>"]
    if title:
        parts.append(f"<h1>{lxml.html.fromstring(title).text_content()}</h1>")
    if body.strip():
        parts.append(body)
    parts.append("</body></html>")
    return "\n".join(parts)


def _domain_of(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname
    except Exception:
        return None


def _first_sentence(text: str) -> str | None:
    """Naive first-sentence extraction for an excerpt."""
    if not text:
        return None
    # Take up to the first period+space or first 200 chars.
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 >= len(text) or text[i + 1].isspace()):
            excerpt = text[: i + 1].strip()
            return excerpt[:200]
    return text[:200].strip() + "…"
