"""Tests for the Trafilatura fallback extractor."""

from __future__ import annotations

from panopticon.ingest.extractor import ExtractedArticle, _domain_of, _first_sentence


class TestDomainOf:
    def test_standard_url(self) -> None:
        assert _domain_of("https://example.com/path") == "example.com"

    def test_url_with_port(self) -> None:
        assert _domain_of("https://example.com:8080/path") == "example.com"

    def test_invalid_url(self) -> None:
        assert _domain_of("not-a-url") is None


class TestFirstSentence:
    def test_simple(self) -> None:
        assert _first_sentence("Hello. World.") == "Hello."

    def test_single_sentence(self) -> None:
        assert _first_sentence("Just one sentence") == "Just one sentence…"

    def test_empty(self) -> None:
        assert _first_sentence("") is None

    def test_truncated(self) -> None:
        long_text = "x" * 300
        result = _first_sentence(long_text)
        assert result is not None
        assert len(result) <= 203  # 200 + "…"


class TestExtractedArticle:
    def test_construction(self) -> None:
        article = ExtractedArticle(
            url="https://example.com",
            domain="example.com",
            title="Test",
            text_content="Body text",
            content_html="<p>Body text</p>",
            byline="Author",
            excerpt="Body text.",
            site_name="Example",
            published_time="2026-01-01",
        )
        assert article.url == "https://example.com"
        assert article.domain == "example.com"
        assert article.extractor == "trafilatura"

    def test_defaults(self) -> None:
        article = ExtractedArticle(
            url="https://x.com",
            domain=None,
            title=None,
            text_content="",
            content_html=None,
        )
        assert article.byline is None
        assert article.extractor == "trafilatura"


class TestExtractIntegration:
    """Integration-style tests that mock Trafilatura."""

    def test_extract_returns_none_on_invalid_url(self, monkeypatch) -> None:
        import courlan

        monkeypatch.setattr(courlan, "validate_url", lambda url: False)
        from panopticon.ingest.extractor import extract

        result = extract("not-a-valid-url")
        assert result is None
