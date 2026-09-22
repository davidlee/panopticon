"""Umbriel IPC framing — the impure protocol shell (SL-005 design §5.2).

The umbriel analogue of ``niri/protocol.py``: connect ``AF_UNIX``/``SOCK_STREAM``
to the umbriel socket, send the ``subscribe`` request, then yield one
``json.loads`` per line. Unlike niri there is **no ack** — the stream opens
directly with the immediate burst (a full ``windows`` snapshot then a full
``workspaces`` snapshot). Parsing is stdlib ``json`` (SPEC-001 D3) — umbriel
carries **no** python runtime dependency, and nothing here runs on the
``--help`` / arg-parse path (the import is deferred behind ``detect``).

Connect and the first read are bounded by ``connect_timeout`` so a wedged
umbriel (socket accepts, never streams) fails fast instead of stalling startup
(F-5). A connect failure or timeout raises; ``run_watcher`` turns that into a
``compositor_disconnected`` and backs off.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

_SUBSCRIBE_REQUEST = b'{"cmd":"subscribe","events":["windows","workspaces"]}\n'

UMBRIEL_SOCKET_ENV = "UMBRIEL_SOCKET"
XDG_RUNTIME_DIR_ENV = "XDG_RUNTIME_DIR"
WAYLAND_DISPLAY_ENV = "WAYLAND_DISPLAY"


def resolve_socket() -> str:
    """The umbriel socket path: ``$UMBRIEL_SOCKET`` else the derived default.

    Derived path = ``$XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock``. Raises
    ``KeyError`` if ``$UMBRIEL_SOCKET`` is unset and either derivation var is
    missing — the caller (explicit ``--compositor umbriel``) surfaces an
    actionable error; the auto-probe skips umbriel rather than fabricate a
    ``.../umbriel-None.sock`` (DL-8, checked in ``detect``).
    """
    explicit = os.environ.get(UMBRIEL_SOCKET_ENV)
    if explicit:
        return explicit
    runtime_dir = os.environ[XDG_RUNTIME_DIR_ENV]
    display = os.environ[WAYLAND_DISPLAY_ENV]
    return f"{runtime_dir}/umbriel-{display}.sock"


async def frames(sock_path: str, *, connect_timeout: float = 2.0) -> AsyncIterator[dict[str, Any]]:
    """Yield one decoded umbriel event per line over the subscribe stream.

    Connects, sends the ``subscribe`` request (no ack to assert), and yields
    ``json.loads`` per non-empty line. Connect and the first read are bounded by
    ``connect_timeout`` (F-5) so a socket that accepts but never streams fails
    fast; subsequent reads stream unbounded. Raises on connect failure or the
    bounded-read timeout.
    """
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(sock_path), connect_timeout
    )
    try:
        writer.write(_SUBSCRIBE_REQUEST)
        await writer.drain()
        first = await asyncio.wait_for(reader.readline(), connect_timeout)
        if not first:  # immediate EOF — nothing to stream
            return
        if first.strip():
            yield json.loads(first)
        async for line in reader:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
    finally:
        writer.close()
        await writer.wait_closed()


async def probe(sock_path: str, *, connect_timeout: float = 2.0) -> bool:
    """Connect-validate the umbriel subscribe stream, then close (D7 auto-detect).

    Runs the same connect + subscribe as :func:`frames` (bounded, F-5), reads one
    framed line to confirm the stream is live, immediately tears the connection
    down, and returns ``True``. Raises on connect failure, timeout, or an
    immediate EOF (no frame) — ``detect._probe_umbriel`` converts a raise into
    "not reachable". Never streams the rest of the burst.
    """
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(sock_path), connect_timeout
    )
    try:
        writer.write(_SUBSCRIBE_REQUEST)
        await writer.drain()
        first = await asyncio.wait_for(reader.readline(), connect_timeout)
        if not first:  # immediate EOF — not a live umbriel stream
            raise ConnectionError(f"umbriel socket {sock_path} closed without streaming")
        return True
    finally:
        writer.close()
        await writer.wait_closed()
