"""i3ipc-python adapter implementing :class:`AsyncSwayClient`.

The adapter is the only module that imports i3ipc; all other watcher
modules deal in the abstract :class:`~panopticon.sway_watcher.runner.AsyncSession`
/ :class:`~panopticon.sway_watcher.runner.AsyncSwayClient` protocols.
Swap providers (e.g. wlroots, kde) by writing another adapter without
touching the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import i3ipc.aio  # type: ignore[import-untyped]

from panopticon.compositor.sway.project import IpcEvent

SUBSCRIBE_EVENTS: tuple[str, ...] = (
    "window",
    "workspace",
    "binding",
    "mode",
    "output",
    "input",
    "shutdown",
)


class I3ipcSession:
    """One live i3ipc connection wrapped as an :class:`AsyncSession`."""

    def __init__(
        self,
        conn: i3ipc.aio.Connection,
        event_iter_factory: Callable[[], AsyncIterator[IpcEvent]],
    ) -> None:
        self._conn = conn
        self._event_iter_factory = event_iter_factory

    def events(self) -> AsyncIterator[IpcEvent]:
        return self._event_iter_factory()

    async def get_tree(self) -> dict[str, Any]:
        tree = await self._conn.get_tree()
        return tree.ipc_data


class I3ipcSwayClient:
    """An :class:`AsyncSwayClient` backed by ``i3ipc.aio.Connection``."""

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

        async def iterate() -> AsyncIterator[IpcEvent]:
            while True:
                item = await queue.get()
                if item is done_sentinel:
                    return
                yield item

        try:
            yield I3ipcSession(conn, iterate)
        finally:
            if not main_task.done():
                main_task.cancel()
                try:
                    await main_task
                except (asyncio.CancelledError, Exception):
                    pass
