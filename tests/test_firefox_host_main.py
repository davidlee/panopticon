"""End-to-end tests for the firefox-host run loop and manifest install."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

from panopticon.firefox_host import install as install_mod
from panopticon.firefox_host.__main__ import main, run_loop
from panopticon.ingest.content import ContentStore, content_dir
from panopticon.schema import iter_jsonl
from panopticon.store import RawStore


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def test_run_loop_writes_event_to_store(tmp_path: Path) -> None:
    msg = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "window_id": 7,
        "tab_id": 42,
        "url": "https://example.com/path?q=1#f",
        "title": "Example",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    events = list(iter_jsonl(out.read_text().splitlines()))
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "firefox"
    assert ev.event == "browser_tab_active"
    assert ev.fields["url"] == "https://example.com/path"
    assert ev.fields["domain"] == "example.com"
    assert ev.fields["window_id"] == 7
    assert ev.fields["title"] == "Example"


def test_run_loop_drops_incognito(tmp_path: Path) -> None:
    msg = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "incognito": True,
        "url": "https://example.com/",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    assert not out.exists()


def test_run_loop_drops_sensitive_scheme(tmp_path: Path) -> None:
    msg = {
        "event": "browser_navigation",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "about:preferences",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    assert not out.exists()


def test_run_loop_overrides_source(tmp_path: Path) -> None:
    msg = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "source": "spoofed",
        "url": "https://example.com/",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    events = list(iter_jsonl(out.read_text().splitlines()))
    assert events[0].source == "firefox"


def test_run_loop_continues_after_malformed_frame(tmp_path: Path) -> None:
    bad = struct.pack("<I", 6) + b"{notjs"
    good = _frame(
        {
            "event": "browser_tab_active",
            "ts": "2026-05-19T10:00:00.000+10:00",
            "url": "https://example.com/",
        }
    )
    stdin = io.BytesIO(bad + good)
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    events = list(iter_jsonl(out.read_text().splitlines()))
    assert len(events) == 1


def test_run_loop_multiple_events(tmp_path: Path) -> None:
    msgs = [
        {
            "event": "browser_tab_active",
            "ts": "2026-05-19T10:00:00.000+10:00",
            "url": "https://a.example/",
        },
        {
            "event": "browser_navigation",
            "ts": "2026-05-19T10:00:05.000+10:00",
            "url": "https://b.example/",
            "kind": "committed",
        },
    ]
    stdin = io.BytesIO(b"".join(_frame(m) for m in msgs))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    events = list(iter_jsonl(out.read_text().splitlines()))
    assert [e.event for e in events] == ["browser_tab_active", "browser_navigation"]
    assert events[1].fields["kind"] == "committed"


def test_install_manifest_print_subcommand(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    fake_bin = tmp_path / "panopticon-firefox-host"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    rc = main(
        [
            "install-manifest",
            "--binary",
            str(fake_bin),
            "--print",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    parsed = json.loads(captured.out)
    assert parsed["name"] == install_mod.HOST_NAME
    assert parsed["path"] == str(fake_bin)
    assert parsed["allowed_extensions"] == [install_mod.EXTENSION_ID]


def test_firefox_launcher_argv_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """Firefox launches the host with [manifest_path, extension_id] as argv;
    argparse must not choke on them."""
    msg = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/",
    }
    stdin = io.BytesIO(_frame(msg))
    monkeypatch.setattr("sys.stdin", type("S", (), {"buffer": stdin})())
    rc = main(
        [
            "/home/u/.mozilla/native-messaging-hosts/panopticon_firefox.json",
            "panopticon-firefox@panopticon.local",
            "--root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    assert out.exists()


def test_install_manifest_writes_file(tmp_path: Path) -> None:
    fake_bin = tmp_path / "panopticon-firefox-host"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    target = tmp_path / "manifest.json"
    rc = main(
        [
            "install-manifest",
            "--binary",
            str(fake_bin),
            "--manifest-path",
            str(target),
        ]
    )
    assert rc == 0
    parsed = json.loads(target.read_text())
    assert parsed["path"] == str(fake_bin)


# ── content extraction routing ───────────────────────────────────────


def test_run_loop_routes_content_extracted_to_content_store(tmp_path: Path) -> None:
    """browser_content_extracted events bypass RawStore, go to ContentStore."""
    msg = {
        "event": "browser_content_extracted",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/article",
        "domain": "example.com",
        "title": "Test Article",
        "textContent": "This is a substantial article body. " * 25,
        "contentHtml": "<p>This is a substantial article body.</p>",
        "length": 750,
        "capturedAt": "2026-05-19T10:00:00.000+10:00",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    # Raw store should NOT have this event.
    raw_out = tmp_path / "raw"
    if raw_out.exists():
        raw_files = list(raw_out.glob("*.jsonl"))
        assert len(raw_files) == 0

    # Content store should have the article.
    ct_root = content_dir()
    assert (ct_root / "articles.jsonl").exists()
    cstore = ContentStore(root=ct_root, domain="example.com")
    articles = cstore.list_articles()
    assert len(articles) >= 1
    assert any(a["url"] == "https://example.com/article" for a in articles)


def test_run_loop_skips_empty_content_extracted(tmp_path: Path) -> None:
    """Content-extracted with empty textContent is skipped."""
    msg = {
        "event": "browser_content_extracted",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/empty",
        "domain": "example.com",
        "title": "Empty",
        "textContent": "",
        "contentHtml": "",
        "length": 0,
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    ct_root = content_dir()
    cstore = ContentStore(root=ct_root, domain="example.com")
    articles = cstore.list_articles()
    assert not any(a["url"] == "https://example.com/empty" for a in articles)


def test_run_loop_skips_content_extracted_error(tmp_path: Path) -> None:
    """Content-extracted with an error field is skipped."""
    msg = {
        "event": "browser_content_extracted",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/fail",
        "domain": "example.com",
        "error": "readability_returned_null",
    }
    stdin = io.BytesIO(_frame(msg))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store)

    ct_root = content_dir()
    cstore = ContentStore(root=ct_root, domain="example.com")
    articles = cstore.list_articles()
    assert not any(a["url"] == "https://example.com/fail" for a in articles)
