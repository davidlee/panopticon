"""The gate audit (SL-008 design §5.2, D5, D6, I6).

Pure. Reads stored digest records and the current gate policy; finds pages the
model flagged as private that the gate would still send, and proposes a deny
entry for each. Advisory only: the flag is model output about a page that has
already left the host, so it never gates.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from panopticon.digest.gate import (
    GateConfig,
    Pass,
    Reason,
    Reject,
    gate,
    normalise_deny_entry,
    normalise_path,
)
from panopticon.digest.prompt import PrivateSurface

FLAGGED_SINCE = 4  # the first PROMPT_VERSION that asks for private_surface


class Skip(StrEnum):
    """Why a record is counted but not listed."""

    MALFORMED = "malformed"
    UNFLAGGED = "unflagged"  # written before the flag existed
    PUBLIC = "public"
    COVERED = "covered"  # the current gate would no longer send it


@dataclass(frozen=True)
class Flagged:
    sha: str
    surface: PrivateSurface
    url: str
    host: str
    title: str | None
    candidate: str


@dataclass(frozen=True)
class Report:
    flagged: tuple[Flagged, ...]
    candidates: tuple[tuple[str, int], ...]  # (deny entry, distinct URLs), most first
    counts: Mapping[str, int]  # by surface and by Skip


def audit_records(
    records: Iterable[tuple[str, Mapping[str, Any] | None]], cfg: GateConfig
) -> Report:
    flagged: list[Flagged] = []
    counts: Counter[str] = Counter()
    for sha, record in records:
        outcome = classify(sha, record, cfg)
        if isinstance(outcome, Flagged):
            flagged.append(outcome)
            counts[outcome.surface] += 1
        else:
            counts[outcome] += 1
    urls: dict[str, set[str]] = {}
    for f in flagged:
        urls.setdefault(f.candidate, set()).add(f.url)
    ranked = sorted(urls.items(), key=lambda kv: -len(kv[1]))
    return Report(tuple(flagged), tuple((e, len(u)) for e, u in ranked), dict(counts))


def classify(sha: str, record: Mapping[str, Any] | None, cfg: GateConfig) -> Flagged | Skip:
    if record is None:
        return Skip.MALFORMED
    url, title, surface = record.get("url"), record.get("title"), record.get("private_surface")
    version = _version(record.get("prompt_version"))
    if (
        not isinstance(url, str)
        or not (title is None or isinstance(title, str))
        or version is None
        or not (surface is None or (isinstance(surface, str) and surface in PrivateSurface))
    ):
        return Skip.MALFORMED
    if version < FLAGGED_SINCE:
        return Skip.UNFLAGGED
    if surface is None:
        return Skip.MALFORMED
    if surface == PrivateSurface.PUBLIC:
        return Skip.PUBLIC
    verdict = _regate(url, cfg)
    if isinstance(verdict, Reject):
        return Skip.COVERED
    return Flagged(
        sha, PrivateSurface(surface), url, verdict.host, title, candidate(url, verdict.host, cfg)
    )


def candidate(url: str, host: str, cfg: GateConfig) -> str:
    """The narrowest useful deny entry that parses and denies ``url`` (I6).

    ``host/<first path segment>``, with ``www.`` dropped since hosts match by
    suffix; else the host. The query is never part of an entry, so a
    query-addressed surface widens to its path (D6).
    """
    if host.startswith("www.") and "." in host[4:]:
        host = host[4:]
    first = normalise_path(urlsplit(url).path).split("/")[1]
    narrow = normalise_deny_entry(f"{host}/{first}") if first else None
    if narrow is not None and _denies(narrow, url, cfg):
        return narrow
    return host


def _denies(entry: str, url: str, cfg: GateConfig) -> bool:
    with_entry = replace(cfg, deny=cfg.deny | {entry})
    return _regate(url, with_entry) == Reject(Reason.DENIED_DOMAIN)


def _regate(url: str, cfg: GateConfig) -> Pass | Reject:
    """The gate's privacy rules only: quality and length pass by construction."""
    return gate(url, cfg.min_quality, None, cfg)


def _version(raw: Any) -> int | None:
    return int(raw) if isinstance(raw, str) and raw.isdecimal() else None
