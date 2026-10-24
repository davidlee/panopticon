"""Tests for the captured-page path lookup (`just content-path`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from panopticon.ingest.content import ContentStore, content_hash, shard_path
from tools.content_path import find, main


def _capture(root: Path, url: str, text: str, *, mtime: float) -> Path:
    """Store a page as the host would; pin its .md mtime. Returns the .md path."""
    ContentStore(root=root, domain="example.com").store(
        url=url, title="T", text_content=text, content_html=f"<p>{text}</p>"
    )
    md = shard_path(root, content_hash(text), ".md")
    os.utime(md, (mtime, mtime))
    return md


def test_newest_capture_by_mtime(tmp_path: Path) -> None:
    _capture(tmp_path, "https://a.example/", "alpha", mtime=100)
    b = _capture(tmp_path, "https://b.example/", "beta", mtime=200)
    assert find(tmp_path) == b


def test_resent_unchanged_page_counts_as_newest(tmp_path: Path) -> None:
    # Re-sending identical content adds no index row but rewrites the file.
    _capture(tmp_path, "https://a.example/", "alpha", mtime=100)
    _capture(tmp_path, "https://b.example/", "beta", mtime=200)
    a = _capture(tmp_path, "https://a.example/", "alpha", mtime=300)
    assert find(tmp_path) == a


def test_by_url_matches_after_redaction(tmp_path: Path) -> None:
    a = _capture(tmp_path, "https://a.example/post", "alpha", mtime=100)
    _capture(tmp_path, "https://b.example/", "beta", mtime=200)
    assert find(tmp_path, "https://a.example/post?utm_source=x#top") == a


def test_by_url_prefers_newest_version(tmp_path: Path) -> None:
    _capture(tmp_path, "https://a.example/", "old text", mtime=100)
    new = _capture(tmp_path, "https://a.example/", "new text", mtime=200)
    assert find(tmp_path, "https://a.example/") == new


def test_nothing_found(tmp_path: Path) -> None:
    assert find(tmp_path) is None
    _capture(tmp_path, "https://a.example/", "alpha", mtime=100)
    assert find(tmp_path, "https://other.example/") is None
    assert find(tmp_path, "about:config") is None


def test_main_prints_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _capture(tmp_path, "https://a.example/", "alpha", mtime=100)
    assert main([], root=tmp_path) == 0
    assert capsys.readouterr().out == f"{a}\n"


def test_main_reports_miss(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["https://a.example/"], root=tmp_path) == 1
    assert "no capture" in capsys.readouterr().err
