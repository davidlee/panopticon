"""Per-tier retention policy for ``~/.local/state/behaviour/``.

Three tiers, three rules:

- ``raw/`` keeps the last ``raw_days`` (default 7). A raw file is only
  deleted once a corresponding segments file exists for the same day —
  unsegmented raw is preserved indefinitely so a missed segmentizer run
  cannot lose data.
- ``segments/`` keeps the last ``segment_days`` (default 90).
- ``histograms/`` is retained forever and never touched here.

All operations are pure unlinks; segment/histogram producers handle
their own atomic-rename writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetentionReport:
    removed_raw: list[Path] = field(default_factory=list)
    skipped_raw_unsegmented: list[Path] = field(default_factory=list)
    removed_segments: list[Path] = field(default_factory=list)


def enforce(
    root: Path,
    *,
    now: date,
    raw_days: int = 7,
    segment_days: int = 90,
) -> RetentionReport:
    """Apply retention rules under ``root`` and return what was touched."""
    removed_raw: list[Path] = []
    skipped: list[Path] = []
    removed_segs: list[Path] = []

    raw_dir = root / "raw"
    seg_dir = root / "segments"

    if raw_dir.is_dir():
        for path in sorted(raw_dir.iterdir()):
            day = _day_from_name(path.name)
            if day is None:
                continue
            if (now - day).days <= raw_days:
                continue
            if _has_segments_for(seg_dir, day):
                path.unlink()
                removed_raw.append(path)
            else:
                skipped.append(path)

    if seg_dir.is_dir():
        for path in sorted(seg_dir.iterdir()):
            day = _day_from_name(path.name)
            if day is None:
                continue
            if (now - day).days > segment_days:
                path.unlink()
                removed_segs.append(path)

    return RetentionReport(
        removed_raw=removed_raw,
        skipped_raw_unsegmented=skipped,
        removed_segments=removed_segs,
    )


def _day_from_name(name: str) -> date | None:
    stem = name.rsplit(".", 1)[0]
    if len(stem) < 10:
        return None
    try:
        return date.fromisoformat(stem[-10:])
    except ValueError:
        return None


def _has_segments_for(seg_dir: Path, day: date) -> bool:
    if not seg_dir.is_dir():
        return False
    suffix = f"-{day.isoformat()}.jsonl"
    return any(p.name.endswith(suffix) for p in seg_dir.iterdir())
