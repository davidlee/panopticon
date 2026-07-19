"""Aggregate segment events into per-day histograms.

Two segment streams are supported:

* ``focus_segment`` (from sway) — contributes ``per_app_seconds``,
  ``per_workspace_seconds``, and ``per_hour_seconds`` (the desktop-focus
  per-hour bucket).
* ``browser_tab_segment`` (from firefox) — contributes
  ``per_domain_seconds`` and ``per_browser_hour_seconds``.

Both aggregators clip each segment to the requested local day boundary
(derived from the segment's own offset) so a segment that crosses
midnight contributes to both days correctly. Output shape after the
segmentizer merges both passes:

```
{
  "day": "YYYY-MM-DD",
  "per_app_seconds":          {app_id: seconds, ...},
  "per_workspace_seconds":    {workspace: seconds, ...},
  "per_hour_seconds":         [s_0, ..., s_23],
  "per_domain_seconds":       {domain: seconds, ...},
  "per_browser_hour_seconds": [s_0, ..., s_23],
}
```

Callers serialize the merged dict with the standard JSON writer;
numbers are plain floats. No I/O happens here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from panopticon.schema import Event


def aggregate(segments: Iterable[Event], *, day: str) -> dict[str, Any]:
    """Build the sway-focus histogram dict for ``day`` (``YYYY-MM-DD``)."""
    per_app: dict[str, float] = {}
    per_ws: dict[str, float] = {}
    per_hour: list[float] = [0.0] * 24

    for seg in segments:
        if seg.event != "focus_segment":
            continue
        f = seg.fields
        clip_start, clip_end = _clip(f, day)
        if clip_end <= clip_start:
            continue
        duration = (clip_end - clip_start).total_seconds()
        app = f["app_id"]
        # R4: de-conflate same-named workspaces across outputs (niri carries
        # `output`); legacy sway segments omit it and stay byte-identical (D8).
        output = f.get("output")
        ws = f["workspace"]
        ws_key = f"{output}/{ws}" if output is not None else ws
        per_app[app] = per_app.get(app, 0.0) + duration
        per_ws[ws_key] = per_ws.get(ws_key, 0.0) + duration
        _accumulate_hourly(per_hour, clip_start, clip_end)

    return {
        "day": day,
        "per_app_seconds": per_app,
        "per_workspace_seconds": per_ws,
        "per_hour_seconds": per_hour,
    }


def aggregate_browser(segments: Iterable[Event], *, day: str) -> dict[str, Any]:
    """Build the browser-segment histogram dict for ``day``."""
    per_domain: dict[str, float] = {}
    per_hour: list[float] = [0.0] * 24

    for seg in segments:
        if seg.event != "browser_tab_segment":
            continue
        f = seg.fields
        clip_start, clip_end = _clip(f, day)
        if clip_end <= clip_start:
            continue
        duration = (clip_end - clip_start).total_seconds()
        domain = f.get("domain") or "(unknown)"
        per_domain[domain] = per_domain.get(domain, 0.0) + duration
        _accumulate_hourly(per_hour, clip_start, clip_end)

    return {
        "day": day,
        "per_domain_seconds": per_domain,
        "per_browser_hour_seconds": per_hour,
    }


def _clip(fields: dict[str, Any], day: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(fields["start_ts"])
    end = datetime.fromisoformat(fields["end_ts"])
    tz = start.tzinfo
    day_start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    return max(start, day_start), min(end, day_end)


def _accumulate_hourly(
    per_hour: list[float], clip_start: datetime, clip_end: datetime
) -> None:
    cur = clip_start
    while cur < clip_end:
        next_hour = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        chunk_end = min(next_hour, clip_end)
        per_hour[cur.hour] += (chunk_end - cur).total_seconds()
        cur = chunk_end
