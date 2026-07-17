"""Derive ``focus_segment`` events from raw desktop-focus JSONL events.

A focus segment is a contiguous interval where the focus key
``(producer, output, app_id, workspace)`` stays the same (D8 — output and
producer keep same-named workspaces on different compositors/outputs from
conflating). The derivation is pure: an :class:`~panopticon.schema.Event`
stream goes in, ``focus_segment`` events come out. Callers route the
output to ``segments/focus-YYYY-MM-DD.jsonl``.

Transitions trigger a segment emission. Both ``compositor_disconnected``
and the legacy ``sway_disconnected`` (F6 — historical raws in the
retention window) close the current segment; the next ``snapshot`` after
reconnect starts a fresh one. ``window_title`` events never split. Pass
``close_at`` to emit a trailing segment for the still-open focus state
(typically the end of the day being processed).

Emitted ``focus_segment`` fields: ``app_id``, ``workspace``, ``start_ts``,
``end_ts``, ``duration_s``, optional ``producer``/``output`` (present only
when the source stream carries them — legacy sway raws omit both, keeping
those segments byte-identical), and optional ``last_title`` — the most
recent window title observed during the segment. ``last_title`` is
omitted when no title was observed.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from panopticon.schema import Event, make_event

SEGMENT_EVENT = "focus_segment"


# A focus key is (producer, output, app_id, workspace) — D8. producer/output are
# None for legacy sway raws (which carry neither); the key then reduces to the
# historical (app_id, workspace) behaviour and the emitted body omits both.
FocusKey = tuple[str | None, str | None, str, str]


def derive_segments(
    events: Iterable[Event],
    *,
    source: str = "sway",
    close_at: str | None = None,
) -> Iterator[Event]:
    """Yield ``focus_segment`` events from a stream of desktop-focus events."""
    running: FocusKey | None = None
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


def _next_focus(ev: Event, running: FocusKey | None) -> FocusKey | None:
    name = ev.event
    f = ev.fields
    if name in ("snapshot", "window_focus"):
        app = f.get("app_id")
        ws = f.get("workspace")
        if app is None or ws is None:
            return None
        producer = f.get("producer")
        output = f.get("output")
        if running is not None:  # retain producer/output an event omits (F9)
            producer = producer if producer is not None else running[0]
            output = output if output is not None else running[1]
        return (producer, output, app, ws)
    if name == "workspace_focus":
        if running is None:
            return None
        producer, output, app, ws = running
        new_ws = f.get("workspace")
        new_output = f.get("output")
        return (
            producer,
            new_output if new_output is not None else output,
            app,
            new_ws if new_ws is not None else ws,
        )
    if name in ("sway_disconnected", "compositor_disconnected"):
        return None
    return running


def _segment(
    source: str,
    focus: FocusKey,
    start_ts: str,
    end_ts: str,
    last_title: str | None = None,
) -> Event:
    producer, output, app_id, workspace = focus
    duration = (
        datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)
    ).total_seconds()
    fields: dict[str, object] = {
        "app_id": app_id,
        "workspace": workspace,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_s": duration,
    }
    if producer is not None:
        fields["producer"] = producer
    if output is not None:
        fields["output"] = output
    if last_title is not None:
        fields["last_title"] = last_title
    return make_event(source, SEGMENT_EVENT, ts=start_ts, **fields)
