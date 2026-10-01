"""Tests for the deterministic pre-egress gate (design §5.2, D4)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from panopticon.digest.config import parse_config
from panopticon.digest.gate import (
    DEFAULT_DENY,
    GateConfig,
    Pass,
    Reason,
    Reject,
    gate,
    normalise_deny_entry,
    normalise_host,
)

CFG = GateConfig(
    deny=DEFAULT_DENY | {"bank.com", "git.example/acme"},
    allow=None,
    min_chars=1500,
    min_quality=0.7,
)


def verdict(url: str, quality: float = 1.0, length: int | None = None, cfg: GateConfig = CFG):
    return gate(url, quality, length, cfg)


# normalise_host ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("example.com.", "example.com"),
        ("xn--fa-hia.de", "xn--fa-hia.de"),
        ("my_host.example.com", "my_host.example.com"),
        ("127.0.0.1", "127.0.0.1"),
        ("::1", "::1"),
    ],
)
def test_normalise_host_canonicalises(raw: str, expected: str):
    assert normalise_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        ".",
        "faß.de",
        "a..b",
        ".example.com",
        "example.com..",
        "https://bank.com",
        "bank.com/x",
        "a b.com",
    ],
)
def test_normalise_host_rejects(raw: str):
    assert normalise_host(raw) is None


# normalise_deny_entry ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bank.COM.", "bank.com"),
        ("bank.com/", "bank.com"),
        ("GitHub.com/Acme/", "github.com/acme"),
        ("github.com//acme//repo", "github.com/acme/repo"),
    ],
)
def test_normalise_deny_entry_canonicalises(raw: str, expected: str):
    assert normalise_deny_entry(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "/acme", "https://bank.com", "faß.de/x", "bank.com/a?b", "bank.com/a#b", "bank.com/a b"],
)
def test_normalise_deny_entry_rejects(raw: str):
    assert normalise_deny_entry(raw) is None


# reasons, in table order ---------------------------------------------------


def test_pass_carries_the_normalised_host():
    assert verdict("https://User:pw@WWW.Example.org./a/b?q=1") == Pass("www.example.org")


@pytest.mark.parametrize(
    "url",
    ["http://[::1", "https://faß.de/", "https://a..b/", "ftp://a..b/"],
)
def test_bad_url(url: str):
    assert verdict(url) == Reject(Reason.BAD_URL)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"]
)
def test_bad_scheme(url: str):
    assert verdict(url) == Reject(Reason.BAD_SCHEME)


@pytest.mark.parametrize("url", ["http:///path", "https://", "https://:443/x"])
def test_no_host(url: str):
    assert verdict(url) == Reject(Reason.NO_HOST)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://router/",
        "http://localhost:3000/",
        "http://app.localhost/",
        "http://printer.local/",
        "http://nas.lan/",
        "http://wiki.corp.internal/",
        "http://hub.home.arpa/",
    ],
)
def test_local_host(url: str):
    assert verdict(url) == Reject(Reason.LOCAL_HOST)


def test_local_host_applies_even_when_allowed():
    cfg = replace(CFG, allow=frozenset({"printer.local", "localhost"}))
    assert verdict("http://printer.local/", cfg=cfg) == Reject(Reason.LOCAL_HOST)
    assert verdict("http://localhost/", cfg=cfg) == Reject(Reason.LOCAL_HOST)


@pytest.mark.parametrize(
    "url",
    ["https://bank.com/", "https://www.bank.com/", "https://BANK.com./", "https://a.b.Bank.Com/"],
)
def test_denied_domain_matches_entry_and_subdomains(url: str):
    assert verdict(url) == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize("url", ["https://evilbank.com/", "https://bank.com.evil.org/"])
def test_denied_domain_matches_on_label_boundary_only(url: str):
    assert verdict(url) == Pass(normalise_host(url.split("/")[2]))


@pytest.mark.parametrize(
    "url",
    [
        "https://git.example/acme",
        "https://git.example/acme/",
        "https://git.example/acme/repo/blob/main/x.py",
        "https://www.git.example/acme/repo",
        "https://GIT.example/ACME/Repo",
        "https://git.example//acme/repo",
        "https://git.example/%61cme/repo",
    ],
)
def test_denied_path_matches_the_prefix_and_below(url: str):
    assert verdict(url) == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize(
    "url",
    [
        "https://git.example/",
        "https://git.example/acme2/repo",
        "https://git.example/other/acme",
        "https://evilgit.example/acme",
    ],
)
def test_denied_path_matches_on_segment_boundary_only(url: str):
    assert verdict(url) == Pass(normalise_host(url.split("/")[2]))


def test_allow_never_passes_a_denied_path():
    cfg = replace(CFG, allow=frozenset({"git.example"}))
    assert verdict("https://git.example/acme/repo", cfg=cfg) == Reject(Reason.DENIED_DOMAIN)
    assert verdict("https://git.example/other/repo", cfg=cfg) == Pass("git.example")


def test_allow_never_passes_a_denied_host():
    cfg = replace(CFG, allow=frozenset({"bank.com", "google.com"}))
    assert verdict("https://bank.com/", cfg=cfg) == Reject(Reason.DENIED_DOMAIN)
    assert verdict("https://mail.google.com/", cfg=cfg) == Reject(Reason.DENIED_DOMAIN)


def test_not_allowed_when_allow_is_set():
    cfg = replace(CFG, allow=frozenset({"lwn.net"}))
    assert verdict("https://lwn.net/Articles/1/", cfg=cfg) == Pass("lwn.net")
    assert verdict("https://www.lwn.net/", cfg=cfg) == Pass("www.lwn.net")
    assert verdict("https://example.org/", cfg=cfg) == Reject(Reason.NOT_ALLOWED)
    assert verdict("https://notlwn.net/", cfg=cfg) == Reject(Reason.NOT_ALLOWED)


def test_empty_allow_passes_nothing():
    cfg = replace(CFG, allow=frozenset())
    assert verdict("https://example.org/", cfg=cfg) == Reject(Reason.NOT_ALLOWED)


def test_low_quality():
    assert verdict("https://example.org/", quality=0.69) == Reject(Reason.LOW_QUALITY)
    assert verdict("https://example.org/", quality=0.7) == Pass("example.org")


def test_too_short_only_once_length_is_known():
    assert verdict("https://example.org/", length=None) == Pass("example.org")
    assert verdict("https://example.org/", length=1499) == Reject(Reason.TOO_SHORT)
    assert verdict("https://example.org/", length=1500) == Pass("example.org")


def test_reasons_are_checked_in_table_order():
    cfg = replace(CFG, allow=frozenset({"lwn.net"}))
    # each URL fails several rules; the earliest in the table wins
    assert verdict("ftp://a..b/", 0.0, 0, cfg) == Reject(Reason.BAD_URL)
    assert verdict("file:///x", 0.0, 0, cfg) == Reject(Reason.BAD_SCHEME)
    assert verdict("http://localhost/", 0.0, 0, cfg) == Reject(Reason.LOCAL_HOST)
    assert verdict("https://bank.com/", 0.0, 0, cfg) == Reject(Reason.DENIED_DOMAIN)
    assert verdict("https://example.org/", 0.0, 0, cfg) == Reject(Reason.NOT_ALLOWED)
    assert verdict("https://lwn.net/", 0.0, 0, cfg) == Reject(Reason.LOW_QUALITY)
    assert verdict("https://lwn.net/", 1.0, 0, cfg) == Reject(Reason.TOO_SHORT)


# DEFAULT_DENY --------------------------------------------------------------


def test_default_deny_entries_are_already_normalised():
    assert DEFAULT_DENY
    assert all(normalise_deny_entry(e) == e for e in DEFAULT_DENY)


@pytest.mark.parametrize(
    "host",
    ["mail.google.com", "chatgpt.com", "claude.ai", "app.slack.com", "www.paypal.com", "my.gov.au"],
)
def test_default_deny_covers_the_categories(host: str):
    assert verdict(f"https://{host}/") == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/messaging/thread/1/",
        "https://www.reddit.com/message/inbox",
        "https://github.com/settings/tokens",
        "https://www.amazon.com.au/checkout/p/1",
    ],
)
def test_default_deny_covers_private_paths_on_public_hosts(url: str):
    assert verdict(url) == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/sharing/compose",
        "https://www.linkedin.com/article/edit/1/",
        "https://x.com/compose/post",
        "https://www.reddit.com/submit?type=TEXT",
        "https://medium.com/new-story",
    ],
)
def test_default_deny_covers_compose_surfaces(url: str):
    assert verdict(url) == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/a/../messaging/t",
        "https://www.linkedin.com/./messaging/t",
        "https://www.linkedin.com/%2e%2e/messaging",
        "https://www.linkedin.com/messaging;x/t",
        "https://twitter.com/messages/1",
    ],
)
def test_deny_paths_cannot_be_dodged_by_dot_segments_or_params(url: str):
    assert verdict(url) == Reject(Reason.DENIED_DOMAIN)


@pytest.mark.parametrize("host", ["127.1", "0x7f.1", "10.0.0.010", "example.0x10"])
def test_a_numeric_final_label_is_an_ip_literal_so_local(host: str):
    assert verdict(f"http://{host}/") == Reject(Reason.LOCAL_HOST)


def test_default_deny_leaves_the_public_paths_of_those_hosts():
    assert verdict("https://github.com/rust-lang/rust") == Pass("github.com")


def test_default_deny_applies_when_config_omits_deny():
    cfg = parse_config({"digest": {"model": "vendor/model"}}).gate
    assert verdict("https://mail.google.com/", cfg=cfg) == Reject(Reason.DENIED_DOMAIN)
    assert verdict("https://example.org/", cfg=cfg) == Pass("example.org")
