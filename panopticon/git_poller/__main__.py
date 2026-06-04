"""Entrypoint for ``panopticon-git``.

A single-shot poll over the dev root (intended for a 5-minute systemd timer,
modelled on ``panopticon-segmentize``). Appends byte-compatible git segments to
``segments/git-<day>.jsonl`` and exits.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from panopticon.git_poller.poller import poll
from panopticon.store import state_dir

log = logging.getLogger("panopticon.git")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="panopticon-git",
        description="Host-side git-commit poller (SATAN git-activity sensor).",
    )
    parser.add_argument(
        "--dev-root",
        type=Path,
        default=Path.home() / "dev",
        help="directory whose immediate children are scanned for git repos "
        "(default: ~/dev)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="behaviour state root; defaults to $XDG_STATE_HOME/behaviour or "
        "~/.local/state/behaviour",
    )
    parser.add_argument(
        "--since",
        default="7.days",
        help="git --since horizon enumerated each poll (default: 7.days)",
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
    root = args.state_dir if args.state_dir is not None else state_dir()
    n = poll(args.dev_root, root, since=args.since)
    log.info("git poll complete: %d segment(s) emitted", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
