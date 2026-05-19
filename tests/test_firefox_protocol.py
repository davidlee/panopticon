"""Tests for the native messaging wire protocol."""

from __future__ import annotations

import io
import json
import struct

import pytest

from panopticon.firefox_host import protocol


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def test_read_message_roundtrip() -> None:
    msg = {"event": "browser_tab_active", "ts": "2026-05-19T10:00:00.000+10:00"}
    stream = io.BytesIO(_frame(msg))
    assert protocol.read_message(stream) == msg


def test_read_message_eof_at_header_returns_none() -> None:
    stream = io.BytesIO(b"")
    assert protocol.read_message(stream) is None


def test_read_message_eof_between_messages_returns_none() -> None:
    msg = {"event": "x", "ts": "t"}
    stream = io.BytesIO(_frame(msg))
    assert protocol.read_message(stream) == msg
    assert protocol.read_message(stream) is None


def test_read_message_truncated_header_raises() -> None:
    stream = io.BytesIO(b"\x05\x00")
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_read_message_truncated_body_raises() -> None:
    stream = io.BytesIO(struct.pack("<I", 10) + b"abc")
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_read_message_oversize_raises() -> None:
    stream = io.BytesIO(struct.pack("<I", protocol.MAX_MESSAGE_BYTES + 1))
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_read_message_invalid_json_raises() -> None:
    body = b"{not json"
    stream = io.BytesIO(struct.pack("<I", len(body)) + body)
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_read_message_non_object_raises() -> None:
    body = b'["array"]'
    stream = io.BytesIO(struct.pack("<I", len(body)) + body)
    with pytest.raises(protocol.ProtocolError):
        protocol.read_message(stream)


def test_write_message_roundtrip() -> None:
    out = io.BytesIO()
    msg = {"event": "browser_navigation", "ts": "t"}
    protocol.write_message(out, msg)
    out.seek(0)
    assert protocol.read_message(out) == msg


def test_write_message_oversize_raises() -> None:
    out = io.BytesIO()
    huge = {"x": "a" * (protocol.MAX_MESSAGE_BYTES + 1)}
    with pytest.raises(protocol.ProtocolError):
        protocol.write_message(out, huge)


def test_sequential_frames_parse_independently() -> None:
    a = {"event": "browser_tab_active", "ts": "t1"}
    b = {"event": "browser_navigation", "ts": "t2"}
    stream = io.BytesIO(_frame(a) + _frame(b))
    assert protocol.read_message(stream) == a
    assert protocol.read_message(stream) == b
    assert protocol.read_message(stream) is None
