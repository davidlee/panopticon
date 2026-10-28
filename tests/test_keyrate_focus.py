"""IMP-006: the focused window a key lands in, from the desktop watcher's current state."""

from __future__ import annotations

import pytest

from panopticon.keyrate.focus import window_of

GHOSTTY = "com.mitchellh.ghostty"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("⠙ Review module layout | david", "Review module layout | david"),
        ("◐ Claude Code", "Claude Code"),
        ("◑ Claude Code", "Claude Code"),
        ("✳ Claude Code", "Claude Code"),
        ("~/dev/satan", "~/dev/satan"),
        ("notes.org ◐", "notes.org ◐"),
        ("◐", None),
    ],
)
def test_a_leading_spinner_is_not_part_of_the_title(title, expected):
    assert window_of({"app_id": GHOSTTY, "title": title}) == (GHOSTTY, expected)


def test_a_window_without_a_title_is_still_a_window():
    assert window_of({"app_id": "emacs", "title": None}) == ("emacs", None)


@pytest.mark.parametrize("current", [{}, {"app_id": None, "title": None}, {"app_id": 3}, []])
def test_nothing_focused_is_no_window(current):
    assert window_of(current) is None
