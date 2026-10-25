"""Keyboards and pointers via evdev: discover, follow hotplug, forward raw events.

The only module that touches ``/dev/input``. Each event goes straight to the
caller's ``on_event(type, code, value)``; nothing here stores it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

import evdev

from panopticon.keyrate.count import is_watched

log = logging.getLogger(__name__)

RESCAN_S = 30.0


class Devices:
    def __init__(self, on_event: Callable[[int, int, int], None]) -> None:
        self._on_event = on_event
        self._readers: dict[str, asyncio.Task[None]] = {}

    @property
    def count(self) -> int:
        return len(self._readers)

    async def run(self) -> None:
        """Rescan for new devices forever; a reader ends when its device goes."""
        self._discover()
        if not self._readers:
            log.warning("no readable keyboard or pointer; is the user in the 'input' group?")
        while True:
            await asyncio.sleep(RESCAN_S)
            self._discover()

    def close(self) -> None:
        for task in self._readers.values():
            task.cancel()

    def _discover(self) -> None:
        for path in evdev.list_devices():
            if path in self._readers:
                continue
            try:
                device = evdev.InputDevice(path)
            except OSError as exc:
                log.debug("skip %s: %s", path, exc)
                continue
            if not is_watched(device.capabilities(absinfo=False), device.info.bustype):
                device.close()
                continue
            log.info("watching %s (%s)", path, device.name)
            self._readers[path] = asyncio.create_task(self._read(path, device))

    async def _read(self, path: str, device: evdev.InputDevice) -> None:
        try:
            async for event in device.async_read_loop():
                self._on_event(event.type, event.code, event.value)
        except OSError as exc:
            log.info("device %s gone: %s", path, exc)
        finally:
            self._readers.pop(path, None)
            with contextlib.suppress(OSError):
                device.close()
