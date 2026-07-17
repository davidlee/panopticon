"""i3ipc-python adapter implementing :class:`CompositorClient` for Sway.

The only module that imports i3ipc; every other compositor module deals
in the neutral protocols. It bridges raw i3ipc events into
:class:`~panopticon.compositor.sway.project.IpcEvent`\\ s and hands a
:class:`~panopticon.compositor.sway.session.SwaySession` (events +
``get_tree``) to the runner. Swap compositors by writing another
adapter without touching the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import i3ipc.aio  # type: ignore[import-untyped]

from panopticon.compositor.sway.project import IpcEvent
from panopticon.compositor.sway.session import SwaySession

SUBSCRIBE_EVENTS: tuple[str, ...] = (
    "window",
    "workspace",
    "binding",
    "mode",
    "output",
    "input",
    "shutdown",
)


class I3ipcSwayClient:
    """A :class:`CompositorClient` backed by ``i3ipc.aio.Connection``."""

    producer = "sway"

    def __init__(self, events: tuple[str, ...] = SUBSCRIBE_EVENTS) -> None:
        self._events = events

    def session(self):
        return self._open()

    @asynccontextmanager
    async def _open(self):
        conn = await i3ipc.aio.Connection().connect()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        done_sentinel = object()

        def make_handler(kind: str):
            def handler(_conn: i3ipc.aio.Connection, event: Any) -> None:
                payload = getattr(event, "ipc_data", None)
                if not isinstance(payload, dict):
                    payload = {}
                queue.put_nowait(IpcEvent(kind=kind, payload=dict(payload)))

            return handler

        for kind in self._events:
            conn.on(kind, make_handler(kind))

        async def main_loop() -> None:
            try:
                await conn.main()
            finally:
                queue.put_nowait(done_sentinel)

        main_task = asyncio.create_task(main_loop())

        def iterate() -> AsyncIterator[IpcEvent]:
            async def gen() -> AsyncIterator[IpcEvent]:
                while True:
                    item = await queue.get()
                    if item is done_sentinel:
                        return
                    yield item

            return gen()

        async def get_tree() -> dict[str, Any]:
            tree = await conn.get_tree()
            return tree.ipc_data

        try:
            yield SwaySession(iterate, get_tree)
        finally:
            if not main_task.done():
                main_task.cancel()
                try:
                    await main_task
                except (asyncio.CancelledError, Exception):
                    pass
