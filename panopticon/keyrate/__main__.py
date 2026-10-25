"""Entrypoint for ``panopticon-keyrate``.

Counts key presses and pointer activity from every keyboard and pointer
(:mod:`~panopticon.keyrate.devices`), and once a second:

* writes each closed minute to ``raw/keyrate-*.jsonl`` and, until SATAN reads
  the raw stream, to the retired wpm-daemon's TSV (IMP-005 step 3 removes it);
* sends the live rate to every client of the keyrate socket.

Never records which key, nor when any single event happened.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from panopticon.cli import configure_logging
from panopticon.keyrate.count import Counter, classify
from panopticon.keyrate.live import Hub, default_socket_path, serve_live
from panopticon.keyrate.render import SOURCE, legacy_tsv, minute_event, snapshot_line
from panopticon.store import RawStore

log = logging.getLogger(__name__)


class Broadcaster(Protocol):
    def broadcast(self, line: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Outputs:
    store: RawStore
    legacy_dir: Path | None
    hub: Broadcaster


def tick(counter: Counter, now: float, out: Outputs, devices: int) -> None:
    """Write every minute closed by ``now``, then broadcast the live rate."""
    for row in counter.close_minutes(now):
        start = datetime.fromtimestamp(row.start, UTC).astimezone()
        out.store.write(minute_event(row, start))
        if out.legacy_dir is not None and (tsv := legacy_tsv(row, start)):
            day, line = tsv
            out.legacy_dir.mkdir(parents=True, exist_ok=True)
            with open(out.legacy_dir / f"{day}.tsv", "a", encoding="utf-8") as fh:
                fh.write(line)
    out.hub.broadcast(snapshot_line(counter.snapshot(now), devices))


def _default_legacy_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "satan" / "log" / "wpm"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="panopticon-keyrate",
        description="Key and pointer activity per minute, plus a live rate socket.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="state root; defaults to $XDG_STATE_HOME/behaviour or ~/.local/state/behaviour",
    )
    parser.add_argument(
        "--legacy-dir",
        type=Path,
        default=_default_legacy_dir(),
        help="where to write the wpm-daemon TSV SATAN reads "
        "(default: $XDG_STATE_HOME/satan/log/wpm)",
    )
    parser.add_argument(
        "--no-legacy",
        dest="legacy_dir",
        action="store_const",
        const=None,
        help="write only the raw stream",
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=default_socket_path(),
        help="live feed socket (default: $XDG_RUNTIME_DIR/panopticon/keyrate.sock)",
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
    configure_logging(args.verbose)
    with RawStore(SOURCE, args.state_dir) as store:
        asyncio.run(_serve(args, store))
    return 0


async def _serve(args: argparse.Namespace, store: RawStore) -> None:
    from panopticon.keyrate.devices import Devices  # evdev: only the live daemon needs it

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    counter = Counter(time.time())

    def on_event(ev_type: int, code: int, value: int) -> None:
        if activity := classify(ev_type, code, value):
            counter.record(activity, time.time())

    hub = Hub()
    out = Outputs(store=store, legacy_dir=args.legacy_dir, hub=hub)
    devices = Devices(on_event)
    async with serve_live(args.socket, hub):
        watcher = asyncio.create_task(devices.run())
        try:
            while not stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1 - time.time() % 1)
                tick(counter, time.time(), out, devices.count)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            devices.close()


if __name__ == "__main__":
    raise SystemExit(main())
