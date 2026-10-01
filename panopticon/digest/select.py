"""Candidate selection over the content index (design §5.4 Selection, D5).

Pure: the shell passes in the index rows and the done set. Only the latest SHA
per URL is ever a candidate — by ``captured_at`` parsed as an aware datetime —
and an older SHA is never a fallback when the latest is gated or done.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from panopticon.digest.gate import GateConfig, Reason, Reject, Verdict, gate

type _Key = tuple[datetime, int]  # (captured_at, index position): later wins ties


@dataclass(frozen=True)
class Judged:
    """An index row and its verdict. ``Pass`` rows are the candidates."""

    row: Mapping[str, Any]
    verdict: Verdict


def pending(
    rows: Iterable[Any], done: Collection[str], cfg: GateConfig
) -> list[Judged]:
    """Judge every row; newest first, malformed rows last.

    Precedence per row: ``bad_row``, ``superseded``, ``done``, then the gate
    without ``too_short`` (the page length is not known until the shell reads
    the ``.json``).
    """
    keyed: list[tuple[_Key, Mapping[str, Any]]] = []
    bad: list[Judged] = []
    for i, raw in enumerate(rows):
        row: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        at = _captured_at(row)
        if at is None:
            bad.append(Judged(row, Reject(Reason.BAD_ROW)))
        else:
            keyed.append(((at, i), row))

    latest: dict[str, _Key] = {}
    for key, row in keyed:
        latest[row["url"]] = max(key, latest.get(row["url"], key))

    keyed.sort(key=lambda kr: kr[0], reverse=True)
    judged = [Judged(row, _judge(row, key == latest[row["url"]], done, cfg)) for key, row in keyed]
    return judged + bad


def _judge(
    row: Mapping[str, Any], is_latest: bool, done: Collection[str], cfg: GateConfig
) -> Verdict:
    if not is_latest:
        return Reject(Reason.SUPERSEDED)
    if row["content_hash"] in done:
        return Reject(Reason.DONE)
    return gate(row["url"], row["quality_score"], None, cfg)


def _captured_at(row: Mapping[str, Any]) -> datetime | None:
    """The row's aware ``captured_at``, or ``None`` if the row is malformed."""
    quality = row.get("quality_score")
    well_typed = (
        isinstance(row.get("url"), str)
        and isinstance(row.get("content_hash"), str)
        and isinstance(quality, int | float)
        and not isinstance(quality, bool)
        and math.isfinite(quality)
        and isinstance(row.get("title"), str | None)
        and isinstance(row.get("captured_at"), str)
    )
    if not well_typed:
        return None
    try:
        at = datetime.fromisoformat(row["captured_at"])
    except ValueError:
        return None
    return at if at.tzinfo is not None else None
