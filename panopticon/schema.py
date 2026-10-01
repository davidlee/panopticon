"""Event schema (v=1) for the panopticon JSONL wire format.

Every event is one JSON object on one line, with required top-level
fields ``v``, ``ts``, ``source``, ``event``. Event-specific fields are
carried in :attr:`Event.fields` and round-trip verbatim.

Consumers should skip lines whose ``v`` they don't understand
(:class:`UnsupportedSchemaError`) and skip lines whose shape is invalid
(:class:`MalformedEventError`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1

_REQUIRED_TOP_LEVEL = ("v", "ts", "source", "event")


class MalformedEventError(ValueError):
    """The JSON object is missing required fields or has wrong types."""


class UnsupportedSchemaError(ValueError):
    """The event's ``v`` is not :data:`SCHEMA_VERSION`."""


@dataclass(frozen=True, slots=True)
class Event:
    """A parsed JSONL event. Round-trips losslessly via :meth:`to_dict`."""

    v: int
    ts: str
    source: str
    event: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "ts": self.ts,
            "source": self.source,
            "event": self.event,
            **self.fields,
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Event:
        for key in _REQUIRED_TOP_LEVEL:
            if key not in d:
                raise MalformedEventError(f"missing required field: {key!r}")
        v = d["v"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise MalformedEventError(f"'v' must be int, got {type(v).__name__}")
        if v != SCHEMA_VERSION:
            raise UnsupportedSchemaError(f"unsupported schema version: {v}")
        for key in ("ts", "source", "event"):
            if not isinstance(d[key], str):
                raise MalformedEventError(f"{key!r} must be str, got {type(d[key]).__name__}")
        extras = {k: val for k, val in d.items() if k not in _REQUIRED_TOP_LEVEL}
        return cls(v=v, ts=d["ts"], source=d["source"], event=d["event"], fields=extras)

    @classmethod
    def from_json_line(cls, line: str) -> Event:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedEventError(f"invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise MalformedEventError(
                f"event must be a JSON object, got {type(parsed).__name__}"
            )
        return cls.from_dict(parsed)


def make_event(
    source: str,
    event: str,
    *,
    ts: str | None = None,
    **fields: Any,
) -> Event:
    """Build an :class:`Event` at the current schema version.

    ``ts`` defaults to :func:`utc_now_iso`. ``fields`` is the
    event-specific payload (``app_id``, ``title``, etc.).
    """
    return Event(
        v=SCHEMA_VERSION,
        ts=ts if ts is not None else utc_now_iso(),
        source=source,
        event=event,
        fields=fields,
    )


def utc_now_iso(now: datetime | None = None) -> str:
    """Return an ISO 8601 timestamp with timezone offset.

    Resolves to local time with offset (``+10:00`` etc.) so events are
    human-readable in the producer's locale while remaining unambiguous.
    Millisecond precision.
    """
    if now is None:
        now = datetime.now(UTC).astimezone()
    return now.isoformat(timespec="milliseconds")


def iter_jsonl(lines: Iterable[str]) -> Iterator[Event]:
    """Yield :class:`Event`\\ s parsed from a stream of JSONL lines.

    Silently skips blank lines, malformed lines, and lines whose
    schema version is unknown. Use direct :meth:`Event.from_json_line`
    for strict parsing.
    """
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            yield Event.from_json_line(line)
        except (MalformedEventError, UnsupportedSchemaError):
            continue
