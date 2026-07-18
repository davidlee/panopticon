"""Niri IPC framing — the impure protocol shell (SL-003 design §5.2).

The niri analogue of ``sway/_i3ipc.py``: connect ``AF_UNIX``/``SOCK_STREAM`` to
``$NIRI_SOCKET``, send the ``"EventStream"`` request, assert the
``{"Ok":"Handled"}`` ack, then yield one ``json.loads`` per line. Parsing is
stdlib ``json`` (SPEC-001 D3) — niri carries **no** python runtime dependency,
and nothing here runs on the ``--help`` / arg-parse path.

Connect and the ack read are bounded by ``connect_timeout`` so a wedged niri
(socket accepts, handler hung) fails fast instead of stalling startup (F-5).
A connect failure or bad ack raises; ``run_watcher`` turns that into a
``compositor_disconnected`` and backs off.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

_EVENT_STREAM_REQUEST = b'"EventStream"\n'
_ACK = {"Ok": "Handled"}


async def frames(sock_path: str, *, connect_timeout: float = 2.0) -> AsyncIterator[dict[str, Any]]:
    """Yield one decoded niri event per line over the event stream.

    Raises on connect failure, timeout, or an ack that is not
    ``{"Ok":"Handled"}``.
    """
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(sock_path), connect_timeout
    )
    try:
        writer.write(_EVENT_STREAM_REQUEST)
        await writer.drain()
        ack_line = await asyncio.wait_for(reader.readline(), connect_timeout)
        if json.loads(ack_line) != _ACK:
            raise ValueError(f"unexpected niri ack: {ack_line!r}")
        async for line in reader:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
    finally:
        writer.close()
