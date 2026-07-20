"""Entrypoint for ``panopticon-desktop``.

Resolves ``--compositor auto|sway|niri`` to an adapter via
:func:`~panopticon.compositor.detect.select_client`, wires it into the
neutral :func:`~panopticon.compositor.runner.run_watcher`, and writes the
``source:"desktop"`` stream to ``raw/desktop-*.jsonl`` +
``current/desktop.json``. Installs signal handlers for graceful shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from pathlib import Path

from panopticon.compositor.detect import select_client
from panopticon.compositor.runner import run_watcher
from panopticon.store import RawStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="panopticon-desktop",
        description="Compositor-neutral desktop behaviour watcher.",
    )
    parser.add_argument(
        "--compositor",
        choices=["auto", "sway", "niri"],
        default="auto",
        help="which compositor adapter to use; 'auto' probes for a live one "
        "(default: auto)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="state root; defaults to $XDG_STATE_HOME/behaviour or "
        "~/.local/state/behaviour",
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

    client, _producer = select_client(args.compositor)
    store = RawStore("desktop", args.state_dir)
    try:
        _run(client, store)
    except KeyboardInterrupt:
        return 130
    finally:
        store.close()
    return 0


def _run(client, store) -> None:
    """Run the watcher until a shutdown signal (sync wrapper over asyncio)."""
    asyncio.run(_serve(client, store))


async def _serve(client, store) -> None:
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
