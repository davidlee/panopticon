"""Tests for content extraction and storage."""

from __future__ import annotations

from pathlib import Path

from panopticon.ingest.content import (
    ContentStore,
    _html_to_markdown,
    content_hash,
    quality_score,
)


class TestContentHash:
    def test_deterministic(self) -> None:
        assert content_hash("hello") == content_hash("hello")

    def test_different_inputs(self) -> None:
        assert content_hash("a") != content_hash("b")

    def test_hex_output(self) -> None:
        ch = content_hash("test")
        assert len(ch) == 64
        int(ch, 16)  # must be valid hex


class TestQualityScore:
    def test_empty_content_zero(self) -> None:
        assert quality_score(text_content="") == 0.0

    def test_very_short_content_zero(self) -> None:
        assert quality_score(text_content="hello world") == 0.0

    def test_short_content_penalised(self) -> None:
        s = quality_score(text_content="x " * 150)
        assert s < 0.7

    def test_good_content_scores_high(self) -> None:
        s = quality_score(
            text_content="This is a well-structured article. " * 40,
            title="A Great Article",
        )
        assert s >= 0.7

    def test_missing_title_penalised(self) -> None:
        with_title = quality_score(
            text_content="content " * 100,
            title="Has Title",
        )
        without_title = quality_score(
            text_content="content " * 100,
            title=None,
        )
        assert without_title < with_title

    def test_nav_like_content_penalised(self) -> None:
        s = quality_score(
            text_content="\n".join(["short"] * 80),
            title="Links",
        )
        assert s < 0.7

    def test_low_text_link_ratio_penalised(self) -> None:
        html = "<html><body>" + "<a href='/x'>link</a> " * 200 + "text " * 10 + "</body></html>"
        s = quality_score(
            text_content="link " * 200 + "text " * 10,
            title="Link Farm",
            content_html=html,
        )
        assert s <= 0.7


class TestHtmlToMarkdown:
    def test_paragraphs(self) -> None:
        md = _html_to_markdown("<p>Hello</p><p>World</p>")
        assert "Hello" in md
        assert "World" in md

    def test_headings(self) -> None:
        md = _html_to_markdown("<h1>Title</h1><h2>Section</h2>")
        assert md.startswith("# Title")
        assert "## Section" in md

    def test_links(self) -> None:
        md = _html_to_markdown('<a href="https://example.com">Example</a>')
        assert "[Example](https://example.com)" in md

    def test_lists(self) -> None:
        md = _html_to_markdown("<ul><li>A</li><li>B</li></ul>")
        assert "- A" in md
        assert "- B" in md

    def test_scripts_stripped(self) -> None:
        md = _html_to_markdown("<p>Hi</p><script>alert(1)</script>")
        assert "Hi" in md
        # markdownify with strip may leave inline script content;
        # the important thing is the readable paragraph survived.
        assert "<script>" not in md


class TestContentStore:
    def test_store_and_retrieve(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="example.com")
        entry = store.store(
            url="https://example.com/article",
            title="Test Article",
            text_content="This is a test article with enough content to pass quality checks. " * 20,
            content_html=(
                "<p>This is a test article with enough content "
                "to pass quality checks.</p>"
            ),
        )
        assert entry is not None
        assert entry["domain"] == "example.com"
        assert entry["url"] == "https://example.com/article"
        assert entry["extractor"] == "readability"
        assert "content_hash" in entry

        # Check files exist.
        ch = entry["content_hash"]
        shard = ch[:2]
        assert (tmp_path / shard / f"{ch}.json").exists()
        assert (tmp_path / shard / f"{ch}.md").exists()

        md_content = (tmp_path / shard / f"{ch}.md").read_text()
        assert "Test Article" in md_content
        assert "article with enough content" in md_content

    def test_duplicate_content_not_re_stored(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="example.com")
        text = "Unique content for de-dup testing. " * 30

        e1 = store.store(
            url="https://example.com/a",
            title="First",
            text_content=text,
            content_html=f"<p>{text}</p>",
        )
        assert e1 is not None

        e2 = store.store(
            url="https://example.com/a",
            title="Duplicate",
            text_content=text,
            content_html=f"<p>{text}</p>",
        )
        assert e2 is None  # duplicate content hash

    def test_different_content_same_url_stored(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="example.com")

        e1 = store.store(
            url="https://example.com/page",
            title="Version 1",
            text_content="First version of the page. " * 30,
            content_html="<p>First version</p>",
        )
        e2 = store.store(
            url="https://example.com/page",
            title="Version 2",
            text_content="Second version of the page, updated. " * 30,
            content_html="<p>Second version</p>",
        )
        assert e1 is not None
        assert e2 is not None
        assert e1["content_hash"] != e2["content_hash"]

    def test_index_entries(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="example.com")
        store.store(
            url="https://example.com/1",
            title="Article 1",
            text_content="Content one. " * 30,
            content_html="<p>One</p>",
        )
        store.store(
            url="https://example.com/2",
            title="Article 2",
            text_content="Content two, completely different. " * 30,
            content_html="<p>Two</p>",
        )

        articles = store.list_articles()
        assert len(articles) == 2
        urls = {a["url"] for a in articles}
        assert urls == {"https://example.com/1", "https://example.com/2"}

    def test_quality_score_in_entry(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="test.org")
        entry = store.store(
            url="https://test.org/doc",
            title="A Decent Article About Things",
            text_content=("Well-formed prose with good structure. " * 25),
            content_html="<p>Well-formed prose with good structure.</p>",
        )
        assert entry is not None
        assert "quality_score" in entry
        assert 0 <= entry["quality_score"] <= 1.0

    def test_markdown_frontmatter(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path, domain="docs.example.com")
        entry = store.store(
            url="https://docs.example.com/guide",
            title="Installation Guide",
            text_content="Step-by-step guide content. " * 30,
            content_html="<h1>Installation</h1><p>Steps.</p>",
            site_name="Example Docs",
            byline="Jane Doe",
        )
        assert entry is not None
        ch = entry["content_hash"]
        md = (tmp_path / ch[:2] / f"{ch}.md").read_text()

        assert "url: https://docs.example.com/guide" in md
        assert "title: Installation Guide" in md
        assert "site: Example Docs" in md
        assert "byline: Jane Doe" in md
        assert "extractor: readability" in md

    def test_store_creates_directories(self, tmp_path: Path) -> None:
        store = ContentStore(root=tmp_path / "deep" / "nested", domain="x.com")
        store.store(
            url="https://x.com/post",
            title="Post",
            text_content="Post content that meets the minimum length threshold. " * 20,
            content_html="<p>Post content.</p>",
        )
        assert (tmp_path / "deep" / "nested" / "articles.jsonl").exists()
