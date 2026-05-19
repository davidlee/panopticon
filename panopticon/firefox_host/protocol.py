"""WebExtension native messaging wire protocol.

Each message is a 4-byte little-endian length prefix followed by that
many bytes of UTF-8 JSON. Firefox enforces a 1 MB per-message cap; this
module enforces the same cap on the receive side and rejects oversized
frames before allocating.

Functions are pure: they take a binary stream and return bytes/dicts.
No logging, no side effects beyond reads/writes on the passed stream.
"""

from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

MAX_MESSAGE_BYTES = 1 << 20  # 1 MiB; Firefox cap.


class ProtocolError(ValueError):
    """A frame header or body violated the native-messaging contract."""


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one framed message from ``stream``.

    Returns ``None`` at clean EOF (zero bytes available before the next
    header). Raises :class:`ProtocolError` for truncated headers,
    oversized payloads, malformed JSON, or a non-object payload.
    """
    header = _read_exact(stream, 4)
    if header is None:
        return None
    (length,) = struct.unpack("<I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message length {length} exceeds {MAX_MESSAGE_BYTES}")
    body = _read_exact(stream, length)
    if body is None:
        raise ProtocolError(f"truncated body: expected {length} bytes, got EOF")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError(f"message must be a JSON object, got {type(parsed).__name__}")
    return parsed


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    """Encode ``payload`` and write the framed bytes to ``stream``."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"encoded message {len(body)} exceeds {MAX_MESSAGE_BYTES}")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def _read_exact(stream: BinaryIO, n: int) -> bytes | None:
    """Read exactly ``n`` bytes. ``None`` on clean EOF before any byte."""
    if n == 0:
        return b""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            if not buf:
                return None
            raise ProtocolError(f"truncated header/body: got {len(buf)} of {n}")
        buf.extend(chunk)
    return bytes(buf)
