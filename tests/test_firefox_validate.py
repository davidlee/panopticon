"""Tests for the firefox-host validator + redactor."""

from __future__ import annotations

import pytest

from panopticon.firefox_host import validate


def test_minimal_valid_message() -> None:
    event, ts, fields = validate.validate_and_redact(
        {
            "event": "browser_tab_active",
            "ts": "2026-05-19T10:00:00.000+10:00",
            "window_id": 7,
            "tab_id": 42,
        }
    )
    assert event == "browser_tab_active"
    assert ts == "2026-05-19T10:00:00.000+10:00"
    assert fields == {"window_id": 7, "tab_id": 42}


def test_missing_event_rejected() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact({"ts": "t"})


def test_missing_ts_rejected() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact({"event": "browser_tab_active"})


def test_unknown_event_rejected() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact({"event": "page_screenshot", "ts": "t"})


def test_source_field_stripped() -> None:
    _, _, fields = validate.validate_and_redact(
        {"event": "browser_tab_active", "ts": "t", "source": "evil"}
    )
    assert "source" not in fields


def test_v_field_stripped() -> None:
    _, _, fields = validate.validate_and_redact(
        {"event": "browser_tab_active", "ts": "t", "v": 99}
    )
    assert "v" not in fields


def test_incognito_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {"event": "browser_tab_active", "ts": "t", "incognito": True}
        )


def test_url_query_and_fragment_stripped() -> None:
    _, _, fields = validate.validate_and_redact(
        {
            "event": "browser_navigation",
            "ts": "t",
            "url": "https://example.com/a/b?token=secret#frag",
        }
    )
    assert fields["url"] == "https://example.com/a/b"
    assert fields["domain"] == "example.com"


def test_about_scheme_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {"event": "browser_navigation", "ts": "t", "url": "about:blank"}
        )


def test_moz_extension_scheme_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {
                "event": "browser_navigation",
                "ts": "t",
                "url": "moz-extension://abc/page.html",
            }
        )


def test_data_scheme_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {
                "event": "browser_navigation",
                "ts": "t",
                "url": "data:text/plain,hi",
            }
        )


def test_file_url_dropped_by_default() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {
                "event": "browser_navigation",
                "ts": "t",
                "url": "file:///home/u/secret.txt",
            }
        )


def test_file_url_allowed_when_enabled() -> None:
    _, _, fields = validate.validate_and_redact(
        {
            "event": "browser_navigation",
            "ts": "t",
            "url": "file:///home/u/notes.md",
        },
        record_file_urls=True,
    )
    assert fields["url"].startswith("file:")


def test_javascript_scheme_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {
                "event": "browser_navigation",
                "ts": "t",
                "url": "javascript:alert(1)",
            }
        )


def test_window_focus_no_url_passes() -> None:
    event, _, fields = validate.validate_and_redact(
        {
            "event": "browser_window_focus",
            "ts": "t",
            "window_id": 3,
            "focused": True,
        }
    )
    assert event == "browser_window_focus"
    assert fields["focused"] is True


def test_idle_state_no_url_passes() -> None:
    event, _, fields = validate.validate_and_redact(
        {"event": "browser_idle_state", "ts": "t", "state": "idle"}
    )
    assert event == "browser_idle_state"
    assert fields["state"] == "idle"


def test_content_extracted_allowed() -> None:
    event, ts, fields = validate.validate_and_redact(
        {
            "event": "browser_content_extracted",
            "ts": "t",
            "url": "https://example.com/post",
            "domain": "example.com",
            "title": "A Post",
            "textContent": "The full article text.",
            "contentHtml": "<p>The full article text.</p>",
            "length": 24,
        }
    )
    assert event == "browser_content_extracted"
    assert fields["url"] == "https://example.com/post"
    assert fields["textContent"] == "The full article text."


def test_uppercase_scheme_dropped() -> None:
    with pytest.raises(validate.ValidationError):
        validate.validate_and_redact(
            {"event": "browser_navigation", "ts": "t", "url": "ABOUT:preferences"}
        )


def test_domain_lowercased() -> None:
    _, _, fields = validate.validate_and_redact(
        {
            "event": "browser_navigation",
            "ts": "t",
            "url": "https://Example.COM/path",
        }
    )
    assert fields["domain"] == "example.com"
