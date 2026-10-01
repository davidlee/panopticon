"""SL-008 VT-2: the gate audit core — classify stored records, propose deny entries."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from panopticon.digest.audit import Flagged, Skip, audit_records, candidate, classify
from panopticon.digest.config import parse_config
from panopticon.digest.gate import GateConfig, Reason, Reject, gate
from panopticon.digest.prompt import PrivateSurface

SHA = "a" * 64
GATE = GateConfig(deny=frozenset({"denied.example"}), allow=None, min_chars=1, min_quality=0.7)


def record(url: str = "https://www.site.example/compose/new", **over: Any) -> dict[str, Any]:
    return {
        "url": url,
        "title": "T",
        "prompt_version": "4",
        "private_surface": "draft",
        **over,
    }


def without(key: str) -> dict[str, Any]:
    return {k: v for k, v in record().items() if k != key}


# classify --------------------------------------------------------------------


def test_a_flagged_exposed_record_is_listed_with_a_candidate():
    assert classify(SHA, record(), GATE) == Flagged(
        sha=SHA,
        surface=PrivateSurface.DRAFT,
        url="https://www.site.example/compose/new",
        host="www.site.example",
        title="T",
        candidate="site.example/compose",
    )


def test_public_is_counted_not_listed():
    assert classify(SHA, record(private_surface="public"), GATE) == Skip.PUBLIC


@pytest.mark.parametrize(
    "cfg",
    [
        replace(GATE, deny=GATE.deny | {"site.example/compose"}),
        replace(GATE, allow=frozenset({"elsewhere.example"})),
    ],
)
def test_a_record_the_current_gate_rejects_is_covered(cfg: GateConfig):
    assert classify(SHA, record(), cfg) == Skip.COVERED


def test_quality_and_length_are_not_privacy_rules():
    # min_quality has no upper bound in the config; it must not hide every record
    assert isinstance(classify(SHA, record(), replace(GATE, min_quality=1.5)), Flagged)
    assert isinstance(classify(SHA, record(), replace(GATE, min_chars=10**9)), Flagged)


@pytest.mark.parametrize("version", ["1", "3"])
def test_records_before_prompt_v4_are_unflagged(version: str):
    assert classify(SHA, without("private_surface") | {"prompt_version": version}, GATE) == (
        Skip.UNFLAGGED
    )


@pytest.mark.parametrize(
    "rec",
    [
        None,
        without("private_surface"),
        record(private_surface="secret"),
        record(private_surface=["draft"]),
        record(private_surface="secret", prompt_version="3"),
        without("url"),
        record(url=7),
        without("prompt_version"),
        record(prompt_version="four"),
        record(title=3),
    ],
)
def test_malformed_records(rec: dict[str, Any] | None):
    assert classify(SHA, rec, GATE) == Skip.MALFORMED


def test_an_unparseable_url_is_covered_since_the_gate_rejects_it():
    assert classify(SHA, record(url="mailto:x@site.example"), GATE) == Skip.COVERED


# candidate -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.site.example/compose/new", "site.example/compose"),
        ("https://site.example/Inbox;s=1/x", "site.example/inbox"),
        ("https://site.example/", "site.example"),
        ("https://site.example/feed?compose=1", "site.example/feed"),
        ("https://site.example/a%3Fb/x", "site.example"),  # decodes to "?": unusable
        ("https://site.example/a%20b/x", "site.example"),  # decodes to a space
        ("https://site.example/../x", "site.example/x"),
        ("https://www.example/x", "www.example/x"),  # never strip down to a bare TLD
    ],
)
def test_candidate(url: str, expected: str):
    host = gate(url, 1.0, None, GATE)
    assert not isinstance(host, Reject)
    assert candidate(url, host.host, GATE) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.site.example/compose/new",
        "https://site.example/a%3Fb",
        "https://site.example/a%1bb/c",
        "https://site.example/%E2%98%83/c",
        "https://site.example/",
    ],
)
def test_every_candidate_parses_as_config_and_denies_its_url(url: str):
    host = gate(url, 1.0, None, GATE)
    assert not isinstance(host, Reject)
    entry = candidate(url, host.host, GATE)
    cfg = parse_config({"digest": {"model": "m"}, "gate": {"deny": [entry]}})
    assert gate(url, 1.0, None, cfg.gate) == Reject(Reason.DENIED_DOMAIN)


# audit_records ---------------------------------------------------------------


def test_report_lists_flagged_counts_everything_and_groups_candidates_by_distinct_url():
    sha = iter(f"{n:064x}" for n in range(100))
    records = [
        (next(sha), record()),
        (next(sha), record()),  # same URL, new content: still one URL
        (next(sha), record(url="https://site.example/compose/other")),
        (next(sha), record(url="https://mail.example/inbox", private_surface="private_message")),
        (next(sha), record(private_surface="public")),
        (next(sha), record(url="https://denied.example/x")),
        (next(sha), without("private_surface") | {"prompt_version": "3"}),
        (next(sha), None),
    ]
    report = audit_records(records, GATE)
    assert [f.surface for f in report.flagged] == ["draft"] * 3 + ["private_message"]
    assert report.candidates == (("site.example/compose", 2), ("mail.example/inbox", 1))
    assert report.counts == {
        "draft": 3,
        "private_message": 1,
        "public": 1,
        "covered": 1,
        "unflagged": 1,
        "malformed": 1,
    }
