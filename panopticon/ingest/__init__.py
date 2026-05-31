"""Content extraction and storage for the panopticon capture pipeline.

Receives extracted article content (Readability JSON from the Firefox
extension, or Trafilatura fallback) and stores it as raw JSON + Markdown
in ``~/.local/state/behaviour/content/``.
"""

from panopticon.ingest.content import ContentStore, content_hash, quality_score

__all__ = ["ContentStore", "content_hash", "quality_score"]
