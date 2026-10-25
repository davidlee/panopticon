"""The live keyrate feed: a private Unix socket that sends one line per tick to every client.

Local only — a Unix socket under ``$XDG_RUNTIME_DIR``, mode 0600 in a 0700
directory. Clients only read; anything they send is ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

log = logging.getLogger(__name__)

MAX_BUFFER = 64 * 1024


def default_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "panopticon" / "keyrate.sock"


class Hub:
    """The connected clients. A client that stops reading is dropped, not waited for."""

    def __init__(self, max_buffer: int = MAX_BUFFER) -> None:
        self._writers: set[asyncio.StreamWriter] = set()
        self._max_buffer = max_buffer

    @property
    def clients(self) -> int:
        return len(self._writers)

    def broadcast(self, line: str) -> None:
        data = line.encode("utf-8")
        for writer in list(self._writers):
            if writer.is_closing():
                self._writers.discard(writer)
                continue
            writer.write(data)
            if writer.transport.get_write_buffer_size() > self._max_buffer:
                log.info("dropping a live client that stopped reading")
                self._drop(writer)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while await reader.read(4096):
                pass
        except ConnectionError:
            pass
        finally:
            self._drop(writer)

    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._writers.discard(writer)
        writer.close()


@contextlib.asynccontextmanager
async def serve_live(path: Path, hub: Hub) -> AsyncIterator[None]:
    """Serve ``hub`` on ``path`` for the duration; the socket is removed on exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.unlink(missing_ok=True)
    old_umask = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(hub.handle, path=path)
    finally:
        os.umask(old_umask)
    try:
        yield
    finally:
        server.close()
        path.unlink(missing_ok=True)
