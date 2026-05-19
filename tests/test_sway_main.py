from __future__ import annotations

from pathlib import Path

import pytest

from panopticon.sway_watcher.__main__ import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.state_dir is None
    assert args.source == "sway"
    assert args.verbose == 0


def test_parse_args_state_dir():
    args = parse_args(["--state-dir", "/tmp/behaviour"])
    assert args.state_dir == Path("/tmp/behaviour")


def test_parse_args_source_override():
    args = parse_args(["--source", "wlroots-experiment"])
    assert args.source == "wlroots-experiment"


def test_parse_args_verbose_counts():
    assert parse_args(["-v"]).verbose == 1
    assert parse_args(["-vv"]).verbose == 2


def test_parse_args_help_exits():
    """argparse prints help and exits cleanly with 0."""
    with pytest.raises(SystemExit) as exc:
        parse_args(["--help"])
    assert exc.value.code == 0
