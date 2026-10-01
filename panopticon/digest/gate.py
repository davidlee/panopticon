"""The deterministic pre-egress gate (design §5.2, D4).

A pure function of the URL, the quality score, the page length and the gate
policy. It decides whether a page may reach a model; a model never does.
Deny entries (``DEFAULT_DENY`` plus the user's) and the local-host rules always
apply; ``allow`` can only narrow what deny lets through.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class Reason(StrEnum):
    """Why a page is not sent. Gate reasons are in rule order; ``pending`` adds the rest."""

    BAD_URL = "bad_url"
    BAD_SCHEME = "bad_scheme"
    NO_HOST = "no_host"
    LOCAL_HOST = "local_host"
    DENIED_DOMAIN = "denied_domain"
    NOT_ALLOWED = "not_allowed"
    LOW_QUALITY = "low_quality"
    TOO_SHORT = "too_short"
    # added by select.pending, which sees the whole index and the done set
    BAD_ROW = "bad_row"
    SUPERSEDED = "superseded"
    DONE = "done"


@dataclass(frozen=True)
class Pass:
    """The page may be sent. ``host`` is the normalised host — the one I1 lets leave."""

    host: str


@dataclass(frozen=True)
class Reject:
    reason: Reason


type Verdict = Pass | Reject


@dataclass(frozen=True)
class GateConfig:
    """Gate policy. ``deny`` already includes ``DEFAULT_DENY``; ``allow=None`` means unset."""

    deny: frozenset[str]
    allow: frozenset[str] | None
    min_chars: int
    min_quality: float


# Generic, widely used hosts by category; none drawn from the user's history
# (design OQ-4). Matching is by label-boundary suffix.
DEFAULT_DENY: frozenset[str] = frozenset(
    {
        # search / Google account surfaces
        "google.com", "bing.com", "duckduckgo.com", "kagi.com", "search.brave.com",
        # mail
        "outlook.live.com", "outlook.office.com", "outlook.office365.com", "proton.me",
        "fastmail.com", "mail.yahoo.com", "icloud.com",
        # chat
        "web.whatsapp.com", "messenger.com", "discord.com", "slack.com",
        "teams.microsoft.com", "teams.live.com", "web.telegram.org",
        # AI chat
        "chatgpt.com", "chat.openai.com", "claude.ai", "gemini.google.com", "perplexity.ai",
        "chat.mistral.ai", "copilot.microsoft.com",
        # office / files
        "office.com", "sharepoint.com", "onedrive.live.com", "live.com", "notion.so",
        "dropbox.com", "box.com",
        # auth / secrets
        "login.microsoftonline.com", "appleid.apple.com", "okta.com", "auth0.com",
        "1password.com", "bitwarden.com",
        # payments / banking
        "paypal.com", "stripe.com", "wise.com", "commbank.com.au", "anz.com.au",
        "westpac.com.au", "nab.com.au",
        # government
        "my.gov.au", "ato.gov.au", "servicesaustralia.gov.au",
    }
)  # fmt: skip

_LOCAL_SUFFIXES = ("localhost", "local", "lan", "internal", "home.arpa")
_LABEL = re.compile(r"[a-z0-9_-]+")


def normalise_host(raw: str) -> str | None:
    """Lowercase, strip one trailing dot; require ASCII LDH(+underscore) labels or an IP literal.

    No IDNA encoding: Firefox serialises hosts as punycode, and stdlib IDNA2003
    disagrees with its UTS46 (``faß.de``). A non-ASCII host is ``None`` (bad_url).
    Restricting label characters also makes a deny entry like ``https://bank.com``
    a config error instead of a silent miss.
    """
    if not raw.isascii():
        return None
    host = raw.lower().removesuffix(".")
    if _is_ip_literal(host):
        return host
    labels = host.split(".")
    if all(_LABEL.fullmatch(label) for label in labels):
        return host
    return None


def gate(url: str, quality: float, length: int | None, cfg: GateConfig) -> Verdict:
    """Apply the §5.2 rules in table order. ``length=None`` defers ``too_short``."""
    try:
        parts = urlsplit(url)
        raw_host = parts.hostname
    except ValueError:
        return Reject(Reason.BAD_URL)
    host = normalise_host(raw_host) if raw_host else None
    if raw_host and host is None:
        return Reject(Reason.BAD_URL)
    if parts.scheme not in ("http", "https"):
        return Reject(Reason.BAD_SCHEME)
    if host is None:
        return Reject(Reason.NO_HOST)
    if _is_local(host):
        return Reject(Reason.LOCAL_HOST)
    if _under_any(host, cfg.deny):
        return Reject(Reason.DENIED_DOMAIN)
    if cfg.allow is not None and not _under_any(host, cfg.allow):
        return Reject(Reason.NOT_ALLOWED)
    if quality < cfg.min_quality:
        return Reject(Reason.LOW_QUALITY)
    if length is not None and length < cfg.min_chars:
        return Reject(Reason.TOO_SHORT)
    return Pass(host)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_local(host: str) -> bool:
    return _is_ip_literal(host) or "." not in host or _under_any(host, _LOCAL_SUFFIXES)


def _under_any(host: str, domains: frozenset[str] | tuple[str, ...]) -> bool:
    """True if ``host`` is a domain in ``domains`` or under one (label boundary)."""
    return any(host == d or host.endswith("." + d) for d in domains)
