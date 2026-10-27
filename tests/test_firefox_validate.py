"""Tests for the firefox-host validator + redactor."""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def _redacted_url(url: str) -> str:
    _, _, fields = validate.validate_and_redact(
        {"event": "browser_navigation", "ts": "t", "url": url}
    )
    return fields["url"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://news.ycombinator.com/item?id=123#c_456",
            "https://news.ycombinator.com/item?id=123",
        ),
        (
            "https://www.youtube.com/watch?t=42&v=abc&list=PL1",
            "https://www.youtube.com/watch?v=abc",
        ),
        ("https://youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"),
        ("https://m.youtube.com/watch?v=abc", "https://m.youtube.com/watch?v=abc"),
        ("https://WWW.YouTube.com/watch?v=abc", "https://WWW.YouTube.com/watch?v=abc"),
    ],
)
def test_identity_params_kept_for_listed_hosts(url: str, expected: str) -> None:
    assert _redacted_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # listed host, identity param absent
        (
            "https://news.ycombinator.com/item?goto=news",
            "https://news.ycombinator.com/item",
        ),
        # identity param name on an unlisted host
        ("https://example.com/item?id=1&v=2", "https://example.com/item"),
        # search terms stay stripped
        ("https://www.google.com/search?q=secret", "https://www.google.com/search"),
        (
            "https://www.youtube.com/results?search_query=secret",
            "https://www.youtube.com/results",
        ),
    ],
)
def test_other_query_params_still_stripped(url: str, expected: str) -> None:
    assert _redacted_url(url) == expected


def test_extension_identity_params_match_host() -> None:
    """The extension's first-pass map must equal the host's (ISS-003)."""
    js = (
        Path(__file__).parent.parent / "firefox-extension" / "background.js"
    ).read_text()
    m = re.search(r"const IDENTITY_PARAMS = (\{.*?\});", js, re.DOTALL)
    assert m, "IDENTITY_PARAMS not found in background.js"
    ext = {host: tuple(names) for host, names in json.loads(m.group(1)).items()}
    assert ext == dict(validate.IDENTITY_PARAMS)


# ── trigger / id normalisation (SL-010 PHASE-01, VT-5) ───────────────


# Well past ContentStore's 500-char quality floor.
_ARTICLE = "A valid article body sentence. " * 30


def _content_message(**overrides: object) -> dict[str, object]:
    """A valid browser_content_extracted message; override any field."""
    msg: dict[str, object] = {
        "event": "browser_content_extracted",
        "ts": "2026-05-19T10:00:00.000+10:00",
        "url": "https://example.com/post",
        "domain": "example.com",
        "title": "A Post",
        "textContent": _ARTICLE,
        "contentHtml": "<p>" + _ARTICLE + "</p>",
        "length": len(_ARTICLE),
    }
    msg.update(overrides)
    return msg


_VALID_ID = "123e4567-e89b-42d3-a456-426614174000"


@pytest.mark.parametrize(
    ("overrides", "trigger", "id_value"),
    [
        ({}, "dwell", None),
        ({"trigger": None}, "dwell", None),
        ({"trigger": "dwell"}, "dwell", None),
        ({"trigger": "bogus"}, "dwell", None),
        ({"trigger": "manual", "id": _VALID_ID}, "manual", _VALID_ID),
        ({"trigger": "manual"}, "dwell", None),
        ({"trigger": "manual", "id": None}, "dwell", None),
        ({"trigger": "manual", "id": ""}, "dwell", None),
        ({"trigger": "manual", "id": "a" * 65}, "dwell", None),
        ({"trigger": "manual", "id": "a b"}, "dwell", None),
        ({"trigger": "manual", "id": 42}, "dwell", None),
        ({"trigger": "manual", "id": ["a"]}, "dwell", None),
    ],
    ids=[
        "absent",
        "null",
        "dwell",
        "unknown",
        "manual-valid-uuid",
        "manual-without-id",
        "manual-null-id",
        "manual-empty-id",
        "manual-oversized-id",
        "manual-space-id",
        "manual-non-string-id",
        "manual-list-id",
    ],
)
def test_trigger_id_normalisation(
    overrides: dict[str, object], trigger: str, id_value: str | None
) -> None:
    """Normalisation never raises; malformed manual requests fall back to dwell.

    ``trigger`` and ``id`` are exposed on ``fields`` for the host's reply
    path; ``run_loop`` pops both before ``fields`` reach ``ContentStore``.
    """
    event, _, fields = validate.validate_and_redact(_content_message(**overrides))
    assert event == "browser_content_extracted"
    assert fields["trigger"] == trigger
    if id_value is None:
        assert "id" not in fields
    else:
        assert fields["id"] == id_value


def test_trigger_and_id_only_on_content_events() -> None:
    """Other events stay as sent: no trigger/id injected into the raw tier."""
    _, _, fields = validate.validate_and_redact(
        {
            "event": "browser_tab_active",
            "ts": "2026-05-19T10:00:00.000+10:00",
            "url": "https://example.com/tab",
        }
    )
    assert "trigger" not in fields
    assert "id" not in fields
