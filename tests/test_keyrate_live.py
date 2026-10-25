"""IMP-005: the live feed — a private Unix socket, one line per tick to every client."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import pytest

from panopticon.keyrate.live import Hub, serve_live


@pytest.fixture
def sock(tmp_path: Path) -> Path:
    return tmp_path / "run" / "panopticon" / "keyrate.sock"


async def _connect(path: Path) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Both ends: dropping the writer would let GC close the connection."""
    return await asyncio.open_unix_connection(path)


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_every_client_gets_each_line(sock: Path):
    hub = Hub()
    async with serve_live(sock, hub):
        (first, _w1), (second, _w2) = await _connect(sock), await _connect(sock)
        await _settle()
        hub.broadcast('{"cpm_5s":12}\n')
        assert await first.readline() == b'{"cpm_5s":12}\n'
        assert await second.readline() == b'{"cpm_5s":12}\n'


async def test_socket_and_its_directory_are_private(sock: Path):
    async with serve_live(sock, Hub()):
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700


async def test_a_stale_socket_is_replaced_and_removed_on_exit(sock: Path):
    sock.parent.mkdir(parents=True)
    sock.write_text("stale")
    async with serve_live(sock, Hub()):
        assert stat.S_ISSOCK(sock.stat().st_mode)
    assert not sock.exists()


async def test_a_departed_client_is_forgotten(sock: Path):
    hub = Hub()
    async with serve_live(sock, hub):
        _reader, writer = await _connect(sock)
        await _settle()
        assert hub.clients == 1
        writer.close()
        await writer.wait_closed()
        await _settle()
        hub.broadcast("x\n")
        await _settle()
        assert hub.clients == 0


async def test_a_client_that_stops_reading_is_dropped(sock: Path):
    hub = Hub(max_buffer=64)
    async with serve_live(sock, hub):
        _idle = await _connect(sock)  # never reads
        await _settle()
        for _ in range(1000):  # well past any kernel socket buffer
            hub.broadcast("x" * 1024 + "\n")
        assert hub.clients == 0
