"""Niri protocol framing over a fake AF_UNIX socket (SL-003 PHASE-01, VT-3).

Drives :func:`frames` with ``asyncio.run`` against an in-process
``asyncio.start_unix_server`` so the suite needs no live niri and no
pytest-asyncio plugin. Asserts the client sends ``"EventStream"``, requires the
``{"Ok":"Handled"}`` ack, yields one dict per line, and that ``connect_timeout``
bounds a socket that accepts but never acks (F-5).
"""

from __future__ import annotations

import asyncio

import pytest

from panopticon.compositor.niri.protocol import frames


async def _serve(tmp_path, handler):
    """Start a unix server at ``tmp_path/niri.sock`` bound to ``handler``."""
    sock = str(tmp_path / "niri.sock")
    server = await asyncio.start_unix_server(handler, path=sock)
    return sock, server


async def _drain_request(reader) -> bytes:
    return await reader.readline()


def test_frames_sends_eventstream_and_yields_events(tmp_path):
    received: list[bytes] = []

    async def scenario():
        async def handler(reader, writer):
            received.append(await _drain_request(reader))
            writer.write(b'{"Ok":"Handled"}\n')
            writer.write(b'{"WorkspacesChanged":{"workspaces":[]}}\n')
            writer.write(b'{"WindowClosed":{"id":7}}\n')
            await writer.drain()
            writer.close()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            out = [event async for event in frames(sock)]
        return out

    events = asyncio.run(scenario())
    assert received == [b'"EventStream"\n']  # exact request framing
    assert events == [
        {"WorkspacesChanged": {"workspaces": []}},
        {"WindowClosed": {"id": 7}},
    ]


def test_frames_rejects_a_bad_ack(tmp_path):
    async def scenario():
        async def handler(reader, writer):
            await _drain_request(reader)
            writer.write(b'{"Ok":"Denied"}\n')
            await writer.drain()
            writer.close()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            with pytest.raises(ValueError, match="unexpected niri ack"):
                async for _ in frames(sock):
                    pass

    asyncio.run(scenario())


def test_connect_timeout_bounds_a_wedged_handler(tmp_path):
    async def scenario():
        release = asyncio.Event()

        async def handler(reader, writer):
            await _drain_request(reader)
            await release.wait()  # accepts, never acks until released
            writer.close()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                async for _ in frames(sock, connect_timeout=0.1):
                    pass
            release.set()  # unwedge so teardown is instant, not timeout-bound

    asyncio.run(scenario())


def test_frames_ignores_blank_lines(tmp_path):
    async def scenario():
        async def handler(reader, writer):
            await _drain_request(reader)
            writer.write(b'{"Ok":"Handled"}\n')
            writer.write(b"\n")  # stray blank line
            writer.write(b'{"WindowClosed":{"id":1}}\n')
            await writer.drain()
            writer.close()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            return [event async for event in frames(sock)]

    assert asyncio.run(scenario()) == [{"WindowClosed": {"id": 1}}]
