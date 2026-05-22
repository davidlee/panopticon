"""Derive ``focus_segment`` events from raw Sway JSONL events.

A focus segment is a contiguous interval where ``(app_id, workspace)``
stays the same. The derivation is pure: an :class:`~panopticon.schema.Event`
stream goes in, ``focus_segment`` events come out. Callers route the
output to ``segments/sway-YYYY-MM-DD.jsonl``.

The function tracks a running ``(app_id, workspace)`` tuple. Transitions
trigger a segment emission. ``sway_disconnected`` closes the current
segment; the next ``snapshot`` after reconnect starts a fresh one.
``window_title`` events never split. Pass ``close_at`` to emit a
trailing segment for the still-open focus state (typically the end of
the day being processed).

Emitted ``focus_segment`` fields: ``app_id``, ``workspace``, ``start_ts``,
``end_ts``, ``duration_s``, and optional ``last_title`` — the most
recent window title observed during the segment (from ``window_focus``,
``window_title``, or ``snapshot`` events). ``last_title`` is omitted
when no title was observed.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from panopticon.schema import Event, make_event

SEGMENT_EVENT = "focus_segment"


def derive_segments(
    events: Iterable[Event],
    *,
    source: str = "sway",
    close_at: str | None = None,
) -> Iterator[Event]:
    """Yield ``focus_segment`` events from a stream of sway events."""
    running: tuple[str, str] | None = None
    start_ts: str | None = None
    last_title: str | None = None

    for ev in events:
        nxt = _next_focus(ev, running)
        title = ev.fields.get("title")
        if not isinstance(title, str):
            title = None

        if nxt == running:
            if title is not None and running is not None:
                last_title = title
            continue

        if running is not None and start_ts is not None:
            yield _segment(source, running, start_ts, ev.ts, last_title)
        running = nxt
        start_ts = ev.ts if nxt is not None else None
        last_title = title if nxt is not None else None

    if running is not None and start_ts is not None and close_at is not None:
        yield _segment(source, running, start_ts, close_at, last_title)


def _next_focus(
    ev: Event, running: tuple[str, str] | None
) -> tuple[str, str] | None:
    name = ev.event
    f = ev.fields
    if name in ("snapshot", "window_focus"):
        app = f.get("app_id")
        ws = f.get("workspace")
        if app is None or ws is None:
            return None
        return (app, ws)
    if name == "workspace_focus":
        if running is None:
            return None
        ws = f.get("workspace")
        if ws is None:
            return running
        return (running[0], ws)
    if name == "sway_disconnected":
        return None
    return running


def _segment(
    source: str,
    focus: tuple[str, str],
    start_ts: str,
    end_ts: str,
    last_title: str | None = None,
) -> Event:
    duration = (
        datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)
    ).total_seconds()
    fields: dict[str, object] = {
        "app_id": focus[0],
        "workspace": focus[1],
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_s": duration,
    }
    if last_title is not None:
        fields["last_title"] = last_title
    return make_event(source, SEGMENT_EVENT, ts=start_ts, **fields)
