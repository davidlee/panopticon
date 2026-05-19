"""Entrypoint for ``panopticon-sway``.

Wires :class:`~panopticon.sway_watcher._i3ipc.I3ipcSwayClient` into
:func:`~panopticon.sway_watcher.runner.run_watcher`, installs signal
handlers for graceful shutdown, and parses CLI args.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from pathlib import Path

from panopticon.store import RawStore
from panopticon.sway_watcher.runner import run_watcher


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="panopticon-sway",
        description="Sway IPC behaviour watcher.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="state root; defaults to $XDG_STATE_HOME/behaviour or "
        "~/.local/state/behaviour",
    )
    parser.add_argument(
        "--source",
        default="sway",
        help="logical source name (per-day filename prefix); default 'sway'",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="increase log verbosity (-v INFO, -vv DEBUG)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    level = max(logging.WARNING - args.verbose * 10, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Defer i3ipc import: parse_args tests don't need the IPC stack
    # loaded, and --help should work even on hosts without i3ipc.
    from panopticon.sway_watcher._i3ipc import I3ipcSwayClient

    client = I3ipcSwayClient()
    store = RawStore(args.source, args.state_dir)
    try:
        asyncio.run(_run(client, store))
    except KeyboardInterrupt:
        return 130
    finally:
        store.close()
    return 0


async def _run(client, store) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    watcher_task = asyncio.create_task(run_watcher(client, store))
    stop_task = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            [watcher_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done:
            watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher_task
        else:
            # Watcher exited on its own — surface any exception.
            stop_task.cancel()
            await watcher_task
    finally:
        if not stop_task.done():
            stop_task.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
