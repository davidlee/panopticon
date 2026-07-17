"""Entrypoint for ``panopticon-segmentize``.

Single-shot batch job (intended for a daily systemd timer):

1. For every ``raw/<source>-YYYY-MM-DD.jsonl`` file, derive
   ``focus_segment`` events and write them atomically to
   ``segments/focus-YYYY-MM-DD.jsonl``. Past days are closed at the next
   day's local midnight (offset taken from the day's last event); the
   in-progress day is closed at its last observed event.
2. For every segment file, build the per-day histogram and write
   ``histograms/daily-YYYY-MM-DD.json`` atomically.
3. Enforce retention.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from panopticon.schema import Event, iter_jsonl
from panopticon.segmentizer.browser import derive_browser_segments
from panopticon.segmentizer.derive import derive_segments
from panopticon.segmentizer.histogram import aggregate, aggregate_browser
from panopticon.segmentizer.retention import enforce
from panopticon.store import state_dir

log = logging.getLogger("panopticon.segmentizer")

# Per-source pipeline: (raw filename prefix, segment filename prefix, derive fn).
# Adding a producer is a one-line change here.
# The desktop watcher (SL-002) emits source='desktop'; the legacy sway entry is
# kept so historical raw/sway-*.jsonl in the retention window still derive
# (source='sway' preserved). Both map to the 'focus' segment prefix — a same-day
# collision would overwrite, but Sway is dormant so no new sway raws arise (R3).
_SOURCES = (
    ("desktop", "focus", derive_segments),
    ("sway", "focus", derive_segments),
    ("firefox", "browser", derive_browser_segments),
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    root = args.root or state_dir()
    today = args.now or date.today()
    run(root, today=today)
    return 0


def run(root: Path, *, today: date) -> None:
    raw_dir = root / "raw"
    if not raw_dir.is_dir():
        log.info("no raw/ at %s; nothing to do", root)
        return

    days_touched: set[str] = set()

    for raw_prefix, seg_prefix, derive in _SOURCES:
        for raw_path in sorted(raw_dir.glob(f"{raw_prefix}-*.jsonl")):
            day_str = _day_from_name(raw_path.name)
            if day_str is None:
                continue
            events = _load_jsonl(raw_path)
            if not events:
                continue
            day = date.fromisoformat(day_str)
            if day < today:
                close_at = _next_day_midnight(day, events[-1].ts)
            else:
                close_at = events[-1].ts
            segs = list(derive(events, source=raw_prefix, close_at=close_at))
            seg_path = root / "segments" / f"{seg_prefix}-{day_str}.jsonl"
            _atomic_write_text(
                seg_path, "".join(s.to_json_line() + "\n" for s in segs)
            )
            log.info("%s %s: %d segments", seg_prefix, day_str, len(segs))
            days_touched.add(day_str)

    for day_str in sorted(days_touched):
        focus_segs = _load_jsonl(root / "segments" / f"focus-{day_str}.jsonl")
        browser_segs = _load_jsonl(root / "segments" / f"browser-{day_str}.jsonl")
        h = aggregate(focus_segs, day=day_str)
        h.update(aggregate_browser(browser_segs, day=day_str))
        hist_path = root / "histograms" / f"daily-{day_str}.json"
        _atomic_write_text(
            hist_path, json.dumps(h, separators=(",", ":"), ensure_ascii=False)
        )
        log.info("histogram %s", day_str)

    report = enforce(root, now=today)
    log.info(
        "retention: removed_raw=%d skipped_unsegmented=%d removed_segments=%d",
        len(report.removed_raw),
        len(report.skipped_raw_unsegmented),
        len(report.removed_segments),
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="panopticon-segmentize")
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="state root (default: $XDG_STATE_HOME/behaviour)",
    )
    p.add_argument(
        "--now",
        type=date.fromisoformat,
        default=None,
        help="treat this date as today (YYYY-MM-DD); default: real today",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="-v INFO, -vv DEBUG",
    )
    return p.parse_args(argv)


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _day_from_name(name: str) -> str | None:
    stem = name.rsplit(".", 1)[0]
    if len(stem) < 10:
        return None
    candidate = stem[-10:]
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def _load_jsonl(path: Path) -> list[Event]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(iter_jsonl(fh))


def _next_day_midnight(day: date, sample_ts: str) -> str:
    dt = datetime.fromisoformat(sample_ts)
    midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=dt.tzinfo)
    return midnight.isoformat(timespec="milliseconds")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
