"""Derive ``browser_tab_segment`` events from raw Firefox JSONL events.

A browser segment is a contiguous interval during which one Firefox
window+tab+URL had focus (within Firefox itself) and the browser was
not idle. The derivation is pure: an :class:`~panopticon.schema.Event`
stream goes in, ``browser_tab_segment`` events come out.

Inputs (event names emitted by the extension):

* ``browser_snapshot``        — opens segment at startup
* ``browser_tab_active``      — closes prior, opens new
* ``browser_tab_updated``     — title/audible changes only; refines
* ``browser_navigation``      — URL change closes/opens
* ``browser_window_focus``    — ``focused=False`` closes; ``True`` reopens
* ``browser_idle_state``      — ``state in {idle, locked}`` closes;
                                 ``active`` does not reopen on its own
                                 (extension is expected to follow with
                                 a tab/navigation event)

Pass ``close_at`` to flush the still-open segment at end of day. The
join with Sway focus segments is downstream of this; we record every
in-browser segment regardless of desktop focus.

TODO: see ``browser.local.md`` "Join with Sway" — that step lives
outside this module so the raw browser segments stay independently
auditable.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from panopticon.schema import Event, make_event

SEGMENT_EVENT = "browser_tab_segment"

_IDLE_CLOSING_STATES = frozenset({"idle", "locked"})


@dataclass(frozen=True, slots=True)
class _Open:
    start_ts: str
    window_id: int | None
    tab_id: int | None
    url: str | None
    domain: str | None
    title_start: str | None
    title_end: str | None
    audible: bool


def derive_browser_segments(
    events: Iterable[Event],
    *,
    source: str = "firefox",
    close_at: str | None = None,
) -> Iterator[Event]:
    """Yield ``browser_tab_segment`` events from a stream of firefox events."""
    cur: _Open | None = None

    for ev in events:
        name = ev.event
        f = ev.fields

        if name in ("browser_snapshot", "browser_tab_active"):
            if cur is not None:
                yield _segment(source, cur, ev.ts)
            cur = _open_from(ev.ts, f)
            continue

        if name == "browser_navigation":
            new_url = f.get("url")
            if cur is None or new_url != cur.url:
                if cur is not None:
                    yield _segment(source, cur, ev.ts)
                cur = _open_from(ev.ts, f)
            continue

        if name == "browser_tab_updated":
            if cur is None:
                continue
            new_url = f.get("url")
            if new_url is not None and new_url != cur.url:
                yield _segment(source, cur, ev.ts)
                cur = _open_from(ev.ts, f)
                continue
            cur = _refine(cur, f)
            continue

        if name == "browser_window_focus":
            if f.get("focused") is False:
                if cur is not None:
                    yield _segment(source, cur, ev.ts)
                    cur = None
            continue

        if name == "browser_idle_state":
            if f.get("state") in _IDLE_CLOSING_STATES:
                if cur is not None:
                    yield _segment(source, cur, ev.ts)
                    cur = None
            continue

    if cur is not None and close_at is not None:
        yield _segment(source, cur, close_at)


def _open_from(ts: str, f: dict[str, Any]) -> _Open:
    title = f.get("title")
    return _Open(
        start_ts=ts,
        window_id=f.get("window_id"),
        tab_id=f.get("tab_id"),
        url=f.get("url"),
        domain=f.get("domain"),
        title_start=title,
        title_end=title,
        audible=bool(f.get("audible", False)),
    )


def _refine(cur: _Open, f: dict[str, Any]) -> _Open:
    new_title = f.get("title")
    new_audible = f.get("audible")
    return replace(
        cur,
        title_end=new_title if new_title is not None else cur.title_end,
        audible=bool(new_audible) if new_audible is not None else cur.audible,
    )


def _segment(source: str, cur: _Open, end_ts: str) -> Event:
    duration = (
        datetime.fromisoformat(end_ts) - datetime.fromisoformat(cur.start_ts)
    ).total_seconds()
    return make_event(
        source,
        SEGMENT_EVENT,
        ts=cur.start_ts,
        start_ts=cur.start_ts,
        end_ts=end_ts,
        duration_s=duration,
        window_id=cur.window_id,
        tab_id=cur.tab_id,
        url=cur.url,
        domain=cur.domain,
        title_start=cur.title_start,
        title_end=cur.title_end,
        audible=cur.audible,
    )
