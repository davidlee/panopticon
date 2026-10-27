"""End-to-end tests for the firefox-host run loop and manifest install."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import pytest

from panopticon.firefox_host import install as install_mod
from panopticon.firefox_host import protocol
from panopticon.firefox_host.__main__ import main, run_loop
from panopticon.ingest.content import ContentStore, content_dir, content_hash, shard_path
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


def test_install_manifest_keeps_profile_symlink(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    """A profile symlink survives rebuilds; its store target does not."""
    real_bin = tmp_path / "store" / "panopticon-firefox-host"
    real_bin.parent.mkdir()
    real_bin.write_text("#!/bin/sh\nexit 0\n")
    real_bin.chmod(0o755)
    profile_bin = tmp_path / "profile" / "bin"
    profile_bin.mkdir(parents=True)
    (profile_bin / "panopticon-firefox-host").symlink_to(real_bin)
    monkeypatch.setenv("PATH", str(profile_bin))  # type: ignore[attr-defined]
    rc = main(["install-manifest", "--print"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert parsed["path"] == str(profile_bin / "panopticon-firefox-host")


def test_install_manifest_refuses_nix_store_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Garbage collection deletes store paths; the manifest would dangle."""
    target = tmp_path / "manifest.json"
    rc = main(
        [
            "install-manifest",
            "--binary",
            "/nix/store/abc-panopticon-0.2.1/bin/panopticon-firefox-host",
            "--manifest-path",
            str(target),
        ]
    )
    assert rc == 1
    assert not target.exists()
    assert "--binary" in caplog.text


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
    ct_root = content_dir(root=tmp_path)
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

    ct_root = content_dir(root=tmp_path)
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

    ct_root = content_dir(root=tmp_path)
    cstore = ContentStore(root=ct_root, domain="example.com")
    articles = cstore.list_articles()
    assert not any(a["url"] == "https://example.com/fail" for a in articles)


# ── reply stream (SL-010 PHASE-01) ───────────────────────────────────


# Comfortably past ContentStore's 500-char quality floor.
_ARTICLE_TEXT = "This is a substantial article body. " * 20  # 740 chars


def _content_msg(**overrides: object) -> dict[str, object]:
    """A valid browser_content_extracted message; override any field."""
    msg: dict[str, object] = {
        "event": "browser_content_extracted",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/article",
        "domain": "example.com",
        "title": "Test Article",
        "textContent": _ARTICLE_TEXT,
        "contentHtml": "<p>" + _ARTICLE_TEXT + "</p>",
        "length": len(_ARTICLE_TEXT),
        "capturedAt": "2026-05-19T10:00:00.000+10:00",
    }
    msg.update(overrides)
    return msg


def _replies(buf: io.BytesIO) -> list[dict]:
    """Decode every framed reply written to ``buf`` (native-messaging framing)."""
    buf.seek(0)
    out: list[dict] = []
    while (msg := protocol.read_message(buf)) is not None:
        out.append(msg)
    return out


def _stored_urls(tmp_path: Path) -> list[str]:
    cstore = ContentStore(root=content_dir(root=tmp_path), domain="example.com")
    return [a["url"] for a in cstore.list_articles()]


def _raw_field_values(tmp_path: Path, key: str) -> list[object]:
    path = tmp_path / "raw" / "firefox-2026-05-19.jsonl"
    if not path.exists():
        return []
    return [ev.fields.get(key) for ev in iter_jsonl(path.read_text().splitlines())]


def test_run_loop_manual_send_replies_content_path(tmp_path: Path) -> None:
    """A manual request gets exactly one ok reply naming the stored .md."""
    stdin = io.BytesIO(_frame(_content_msg(trigger="manual", id="manual-1")))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert len(replies) == 1
    r = replies[0]
    assert r["type"] == "content_path"
    assert r["id"] == "manual-1"
    assert r["ok"] is True

    expected_hash = content_hash(_ARTICLE_TEXT)
    ct_root = content_dir(root=tmp_path)
    expected_path = shard_path(ct_root, expected_hash, ".md")
    assert r["hash"] == expected_hash
    assert r["path"] == str(expected_path)
    assert expected_path.exists()
    assert Path(r["path"]).is_absolute()
    assert Path(r["path"]).is_relative_to(ct_root)
    assert "https://example.com/article" in _stored_urls(tmp_path)


def test_run_loop_manual_duplicate_replies_same_path(tmp_path: Path) -> None:
    """The same text sent twice manually → two ok replies, same path."""
    stdin = io.BytesIO(
        _frame(_content_msg(trigger="manual", id="dup-1"))
        + _frame(_content_msg(trigger="manual", id="dup-2"))
    )
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert [r["id"] for r in replies] == ["dup-1", "dup-2"]
    assert all(r["ok"] is True for r in replies)
    assert replies[0]["path"] == replies[1]["path"]
    assert replies[0]["hash"] == replies[1]["hash"]


def test_run_loop_manual_error_replies_extraction_error(tmp_path: Path) -> None:
    """A manual extraction that reported an error replies, but stores nothing."""
    msg = _content_msg(trigger="manual", id="err-1", error="readability_returned_null")
    stdin = io.BytesIO(_frame(msg))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert len(replies) == 1
    r = replies[0]
    assert r["type"] == "content_path"
    assert r["id"] == "err-1"
    assert r["ok"] is False
    assert r["reason"] == "extraction_error"
    assert "path" not in r
    # The extraction's own error string is never echoed back.
    assert "readability_returned_null" not in json.dumps(r)
    assert _stored_urls(tmp_path) == []


@pytest.mark.parametrize(
    "overrides",
    [{"textContent": ""}, {"contentHtml": ""}],
    ids=["no_text", "no_html"],
)
def test_run_loop_manual_empty_content_replies_empty_content(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    """Empty text or HTML on a manual request → reason empty_content."""
    stdin = io.BytesIO(_frame(_content_msg(trigger="manual", id="empty-1", **overrides)))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert len(replies) == 1
    r = replies[0]
    assert r["type"] == "content_path"
    assert r["id"] == "empty-1"
    assert r["ok"] is False
    assert r["reason"] == "empty_content"
    assert "path" not in r


def test_run_loop_manual_store_failure_replies_store_failed_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising store() becomes store_failed; capture keeps going after it."""

    def boom(self: ContentStore, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ContentStore, "store", boom)
    after = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "window_id": 1,
        "tab_id": 2,
        "url": "https://example.com/after-failure",
    }
    stdin = io.BytesIO(_frame(_content_msg(trigger="manual", id="fail-1")) + _frame(after))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert len(replies) == 1
    r = replies[0]
    assert r["type"] == "content_path"
    assert r["id"] == "fail-1"
    assert r["ok"] is False
    assert r["reason"] == "store_failed"
    assert "path" not in r
    # The loop survived the store exception.
    assert "https://example.com/after-failure" in _raw_field_values(tmp_path, "url")


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"trigger": None},
        {"trigger": "dwell"},
        {"trigger": "bogus"},
        {"trigger": "manual"},
        {"trigger": "manual", "id": None},
        {"trigger": "manual", "id": ""},
        {"trigger": "manual", "id": "a" * 65},
        {"trigger": "manual", "id": "a b"},
        {"trigger": "manual", "id": 42},
    ],
    ids=[
        "absent",
        "null",
        "dwell",
        "unknown",
        "manual-without-id",
        "manual-null-id",
        "manual-empty-id",
        "manual-oversized-id",
        "manual-space-id",
        "manual-non-string-id",
    ],
)
def test_run_loop_dwell_and_invalid_manual_write_no_reply(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    """Non-manual requests are stored as today and put zero bytes on the wire."""
    stdin = io.BytesIO(_frame(_content_msg(**overrides)))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    assert reply.getvalue() == b""
    assert "https://example.com/article" in _stored_urls(tmp_path)


class _BrokenPipeStream(io.BytesIO):
    """A reply stream whose writes always fail, like a vanished extension port."""

    def write(self, b: bytes) -> int:
        raise BrokenPipeError("port closed")


def test_run_loop_broken_pipe_reply_keeps_processing(tmp_path: Path) -> None:
    """A failing reply write is logged and the loop keeps reading."""
    after = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "window_id": 1,
        "tab_id": 2,
        "url": "https://example.com/after-broken-pipe",
    }
    stdin = io.BytesIO(_frame(_content_msg(trigger="manual", id="pipe-1")) + _frame(after))
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=_BrokenPipeStream())

    assert "https://example.com/after-broken-pipe" in _raw_field_values(tmp_path, "url")


def test_run_loop_replies_once_per_manual_request(tmp_path: Path) -> None:
    """Dwell requests are silent; each manual request yields exactly one reply."""
    tab = {
        "event": "browser_tab_active",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "window_id": 1,
        "tab_id": 2,
        "url": "https://example.com/tab",
    }
    stdin = io.BytesIO(
        _frame(_content_msg(trigger="dwell"))
        + _frame(_content_msg(trigger="manual", id="a-1"))
        + _frame(tab)
        + _frame(_content_msg(trigger="manual", id="b-2"))
    )
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    replies = _replies(reply)
    assert [r["id"] for r in replies] == ["a-1", "b-2"]
    assert all(r["type"] == "content_path" for r in replies)


def test_run_loop_strips_trigger_and_id_before_content_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """trigger/id are wire-only: they never reach ContentStore.store()."""
    captured: dict[str, object] = {}
    real_store = ContentStore.store

    def spy(self: ContentStore, **kwargs: object) -> dict | None:
        captured.update(kwargs)
        return real_store(self, **kwargs)

    monkeypatch.setattr(ContentStore, "store", spy)
    stdin = io.BytesIO(_frame(_content_msg(trigger="manual", id="strip-1")))
    reply = io.BytesIO()
    with RawStore(source="firefox", root=tmp_path) as store:
        run_loop(stdin, store, reply=reply)

    assert "trigger" not in captured
    assert "id" not in captured
    assert captured["url"] == "https://example.com/article"
    assert _replies(reply)[0]["ok"] is True
