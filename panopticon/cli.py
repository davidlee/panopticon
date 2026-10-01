"""Plumbing shared by every ``panopticon-*`` entrypoint."""

from __future__ import annotations

import logging
import sys


def log_level(verbose: int) -> int:
    """WARNING by default; ``-v`` INFO, ``-vv`` (or more) DEBUG."""
    return max(logging.WARNING - 10 * verbose, logging.DEBUG)


def configure_logging(verbose: int) -> None:
    """Log to stderr — stdout may be a protocol (the native-messaging host)."""
    logging.basicConfig(
        level=log_level(verbose),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
