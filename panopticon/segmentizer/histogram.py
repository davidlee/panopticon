"""Aggregate ``focus_segment`` events into per-day histograms.

The aggregator clips each segment to the requested local day boundary
(derived from the segment's own offset) so a segment that crosses
midnight contributes to both days correctly. The output shape:

```
{
  "day": "YYYY-MM-DD",
  "per_app_seconds": {app_id: seconds, ...},
  "per_workspace_seconds": {workspace: seconds, ...},
  "per_hour_seconds": [s_0, s_1, ..., s_23],   # local hour buckets
}
```

Callers serialize this with the standard JSON writer; numbers are
plain floats. No I/O happens here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from panopticon.schema import Event


def aggregate(segments: Iterable[Event], *, day: str) -> dict[str, Any]:
    """Build a histogram dict for ``day`` (``YYYY-MM-DD``)."""
    per_app: dict[str, float] = {}
    per_ws: dict[str, float] = {}
    per_hour: list[float] = [0.0] * 24

    for seg in segments:
        f = seg.fields
        start = datetime.fromisoformat(f["start_ts"])
        end = datetime.fromisoformat(f["end_ts"])
        tz = start.tzinfo
        day_start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=tz)
        day_end = day_start + timedelta(days=1)

        clip_start = max(start, day_start)
        clip_end = min(end, day_end)
        if clip_end <= clip_start:
            continue

        duration = (clip_end - clip_start).total_seconds()
        app = f["app_id"]
        ws = f["workspace"]
        per_app[app] = per_app.get(app, 0.0) + duration
        per_ws[ws] = per_ws.get(ws, 0.0) + duration

        cur = clip_start
        while cur < clip_end:
            next_hour = (
                cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            )
            chunk_end = min(next_hour, clip_end)
            per_hour[cur.hour] += (chunk_end - cur).total_seconds()
            cur = chunk_end

    return {
        "day": day,
        "per_app_seconds": per_app,
        "per_workspace_seconds": per_ws,
        "per_hour_seconds": per_hour,
    }
