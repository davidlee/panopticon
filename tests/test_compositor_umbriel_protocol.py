"""Umbriel protocol framing over a fake AF_UNIX socket (SL-005 PHASE-01, VT-6).

Drives :func:`frames` with ``asyncio.run`` against an in-process
``asyncio.start_unix_server`` so the suite needs no live umbriel. Asserts the
client sends the ``subscribe`` request, that there is **no ack** (the stream
opens directly with the burst), that it yields one dict per line, and that
``connect_timeout`` bounds a socket that accepts but never streams (F-5 / §5.2).
:func:`resolve_socket` env precedence is a pure lookup.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from panopticon.compositor.umbriel.protocol import frames, resolve_socket

_SUBSCRIBE = {"cmd": "subscribe", "events": ["windows", "workspaces"]}


# ---- resolve_socket (env precedence) ----------------------------------------


def test_resolve_socket_prefers_umbriel_socket_env(monkeypatch):
    monkeypatch.setenv("UMBRIEL_SOCKET", "/run/user/1000/umbriel.sock")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert resolve_socket() == "/run/user/1000/umbriel.sock"


def test_resolve_socket_derives_from_xdg_and_display(monkeypatch):
    monkeypatch.delenv("UMBRIEL_SOCKET", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    assert resolve_socket() == "/run/user/1000/umbriel-wayland-1.sock"


# ---- frames (fake unix server) ----------------------------------------------


async def _serve(tmp_path, handler):
    sock = str(tmp_path / "umbriel.sock")
    server = await asyncio.start_unix_server(handler, path=sock)
    return sock, server


def test_frames_sends_subscribe_and_yields_events(tmp_path):
    received: list[bytes] = []

    async def scenario():
        async def handler(reader, writer):
            received.append(await reader.readline())
            # No ack — the stream opens directly with the burst.
            writer.write(b'{"event":"windows","data":[]}\n')
            writer.write(b'{"event":"workspaces","data":[]}\n')
            await writer.drain()
            writer.close()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            out = [event async for event in frames(sock)]
        return out

    events = asyncio.run(scenario())
    assert json.loads(received[0]) == _SUBSCRIBE  # exact request framing, no ack
    assert events == [
        {"event": "windows", "data": []},
        {"event": "workspaces", "data": []},
    ]


def test_frames_connect_timeout_bounds_silent_socket(tmp_path):
    """A socket that accepts but never streams must fail fast, not hang (§5.2)."""

    async def scenario():
        release = asyncio.Event()

        async def handler(reader, writer):
            await reader.readline()  # consume subscribe, then stay silent (open)
            await release.wait()

        sock, server = await _serve(tmp_path, handler)
        async with server:
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                async for _ in frames(sock, connect_timeout=0.05):
                    pass
            release.set()  # unwedge so teardown is instant, not timeout-bound

    asyncio.run(scenario())
