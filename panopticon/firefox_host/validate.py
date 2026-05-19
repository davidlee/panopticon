"""Server-side validation, redaction, and source enforcement.

The extension is expected to do most filtering, but this host re-applies
every privacy rule as defence-in-depth: a buggy or hostile extension
must not be able to slip a banking URL through by skipping its own
filter. All functions are pure.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

SENSITIVE_SCHEMES = frozenset(
    {
        "about",
        "moz-extension",
        "chrome",
        "resource",
        "view-source",
        "data",
        "blob",
        "javascript",
    }
)

ALLOWED_EVENT_TYPES = frozenset(
    {
        "browser_snapshot",
        "browser_tab_active",
        "browser_tab_updated",
        "browser_navigation",
        "browser_window_focus",
        "browser_idle_state",
    }
)


class ValidationError(ValueError):
    """The incoming message is not a valid browser event."""


def validate_and_redact(
    message: dict[str, Any],
    *,
    record_file_urls: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """Validate and redact a raw message from the extension.

    Returns ``(event_name, ts, fields)`` ready for
    :func:`panopticon.schema.make_event`. Raises
    :class:`ValidationError` if the message should be dropped entirely
    (missing fields, unknown event, sensitive URL scheme, file URL when
    not enabled).
    """
    event = message.get("event")
    ts = message.get("ts")
    if not isinstance(event, str) or not event:
        raise ValidationError("missing 'event'")
    if not isinstance(ts, str) or not ts:
        raise ValidationError("missing 'ts'")
    if event not in ALLOWED_EVENT_TYPES:
        raise ValidationError(f"unknown event type: {event!r}")

    fields = {
        k: v
        for k, v in message.items()
        if k not in ("event", "ts", "v", "source")
    }

    if fields.get("incognito") is True:
        raise ValidationError("incognito event dropped at host")

    url = fields.get("url")
    if isinstance(url, str) and url:
        redacted = _redact_url(url, record_file_urls=record_file_urls)
        if redacted is None:
            raise ValidationError(f"sensitive scheme dropped: {url[:32]}")
        fields["url"] = redacted
        domain = _domain_of(redacted)
        if domain is not None:
            fields["domain"] = domain

    return event, ts, fields


def _redact_url(url: str, *, record_file_urls: bool) -> str | None:
    """Strip query+fragment; drop sensitive schemes. Returns ``None`` to drop."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme in SENSITIVE_SCHEMES:
        return None
    if scheme == "file" and not record_file_urls:
        return None
    if scheme not in ("http", "https", "ftp", "file"):
        return None
    return urlunsplit((scheme, parts.netloc, parts.path, "", ""))


def _domain_of(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None
