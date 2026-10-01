"""Shared CLI plumbing: one verbosity mapping for every binary."""

from __future__ import annotations

import logging

import pytest

from panopticon.cli import log_level


@pytest.mark.parametrize(
    ("verbose", "level"),
    [(0, logging.WARNING), (1, logging.INFO), (2, logging.DEBUG), (5, logging.DEBUG)],
)
def test_log_level_maps_verbosity(verbose: int, level: int):
    assert log_level(verbose) == level
