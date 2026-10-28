"""IMP-005: the keyrate counting core — classification, minute rows, live snapshot."""

from __future__ import annotations

import pytest

from panopticon.keyrate.count import (
    Activity,
    Counter,
    MinuteRow,
    Snapshot,
    WindowRow,
    classify,
    is_watched,
)

EV_KEY, EV_REL, EV_ABS, EV_MSC = 1, 2, 3, 4
KEY_A, KEY_LEFTSHIFT, KEY_RIGHTMETA, KEY_F13 = 30, 42, 126, 183
BTN_LEFT, BTN_TOUCH, BTN_TOOL_PEN = 0x110, 0x14A, 0x140
REL_X, ABS_X = 0, 0
BUS_USB, BUS_BLUETOOTH, BUS_VIRTUAL = 0x03, 0x05, 0x06
PRESS, RELEASE, REPEAT = 1, 0, 2

T0 = 1_800_000_000  # a minute boundary: 1_800_000_000 % 60 == 0


def test_t0_is_a_minute_boundary():
    assert T0 % 60 == 0


@pytest.mark.parametrize(
    ("ev_type", "code", "value", "expected"),
    [
        (EV_KEY, KEY_A, PRESS, Activity.KEY),
        (EV_KEY, KEY_F13, PRESS, Activity.KEY),
        (EV_KEY, KEY_A, RELEASE, None),
        (EV_KEY, KEY_A, REPEAT, None),
        (EV_KEY, KEY_LEFTSHIFT, PRESS, None),
        (EV_KEY, KEY_RIGHTMETA, PRESS, None),
        (EV_KEY, BTN_LEFT, PRESS, Activity.POINTER),
        (EV_KEY, BTN_LEFT, RELEASE, None),
        (EV_REL, REL_X, 3, Activity.POINTER),
        (EV_ABS, ABS_X, 512, Activity.POINTER),
        (EV_MSC, 4, 458756, None),
    ],
)
def test_classify(ev_type, code, value, expected):
    assert classify(ev_type, code, value) is expected


@pytest.mark.parametrize(
    ("capabilities", "watched"),
    [
        ({EV_KEY: [KEY_A, KEY_LEFTSHIFT]}, True),  # keyboard
        ({EV_KEY: [BTN_LEFT], EV_REL: [REL_X]}, True),  # mouse
        ({EV_KEY: [BTN_TOUCH, BTN_LEFT], EV_ABS: [ABS_X]}, True),  # touchpad
        ({EV_KEY: [BTN_TOOL_PEN], EV_ABS: [ABS_X]}, True),  # tablet
        ({EV_KEY: [116]}, False),  # power button
        ({EV_ABS: [ABS_X]}, False),  # accelerometer / joystick axis
        ({}, False),
    ],
)
def test_is_watched(capabilities, watched):
    assert is_watched(capabilities, BUS_USB) is watched


@pytest.mark.parametrize(("bus", "watched"), [(BUS_BLUETOOTH, True), (BUS_VIRTUAL, False)])
def test_software_keyboards_are_not_watched(bus, watched):
    # uinput devices (snippet expanders, ydotool) type for you; BLE keyboards stay in.
    assert is_watched({EV_KEY: [KEY_A]}, bus) is watched


def _record(counter: Counter, activity: Activity, *times: float) -> None:
    for t in times:
        counter.record(activity, t)


def test_closes_a_minute_into_one_row():
    counter = Counter(T0)
    _record(counter, Activity.KEY, T0 + 1.1, T0 + 1.5, T0 + 3.0, T0 + 40.0)
    _record(counter, Activity.POINTER, T0 + 3.2, T0 + 3.9, T0 + 50.0)

    assert counter.close_minutes(T0 + 59.9) == []
    assert counter.close_minutes(T0 + 60.0) == [
        MinuteRow(start=T0, keys=4, key_seconds=3, pointer_seconds=2, peak_5s_cpm=36)
    ]
    assert counter.close_minutes(T0 + 61.0) == []


def test_peak_window_stays_inside_its_minute():
    counter = Counter(T0)
    _record(counter, Activity.KEY, T0 + 58, T0 + 59, T0 + 60, T0 + 61)
    [first] = counter.close_minutes(T0 + 60)
    assert (first.keys, first.peak_5s_cpm) == (2, 24)


def test_quiet_minutes_yield_no_rows_and_a_jump_ahead_skips_them():
    counter = Counter(T0)
    _record(counter, Activity.KEY, T0 + 5)
    _record(counter, Activity.POINTER, T0 + 3 * 3600 + 7)
    rows = counter.close_minutes(T0 + 4 * 3600)
    assert [r.start for r in rows] == [T0, T0 + 3 * 3600]
    assert (rows[1].keys, rows[1].pointer_seconds) == (0, 1)


def test_the_first_minute_may_be_partial():
    counter = Counter(T0 + 30.5)
    _record(counter, Activity.KEY, T0 + 31)
    assert [r.start for r in counter.close_minutes(T0 + 60)] == [T0]


def test_events_for_an_already_closed_minute_are_dropped():
    counter = Counter(T0)
    counter.close_minutes(T0 + 120)
    _record(counter, Activity.KEY, T0 + 10)  # clock stepped back
    assert counter.close_minutes(T0 + 180) == []


def test_snapshot_rates():
    counter = Counter(T0)
    _record(counter, Activity.KEY, *(T0 + 10 + i / 10 for i in range(20)))  # 20 keys at 10s
    _record(counter, Activity.KEY, T0 + 57, T0 + 58.5, T0 + 59.9)
    _record(counter, Activity.POINTER, T0 + 30, T0 + 30.5, T0 + 59)

    assert counter.snapshot(T0 + 59.95) == Snapshot(cpm_5s=36, cpm_60s=23, pointer_seconds_60s=2)
    assert counter.snapshot(T0 + 75) == Snapshot(cpm_5s=0, cpm_60s=3, pointer_seconds_60s=2)
    assert counter.snapshot(T0 + 200) == Snapshot(cpm_5s=0, cpm_60s=0, pointer_seconds_60s=0)


def test_snapshot_survives_closing_the_minute():
    counter = Counter(T0)
    _record(counter, Activity.KEY, T0 + 58, T0 + 59)
    counter.close_minutes(T0 + 60.2)
    assert counter.snapshot(T0 + 60.2).cpm_60s == 2


def test_memory_is_bounded():
    counter = Counter(T0)
    for t in range(T0, T0 + 3600):
        counter.record(Activity.KEY, t)
        counter.close_minutes(t)
        counter.snapshot(t)
    assert counter.retained_seconds() <= 61


EMACS = ("emacs", "notes.org")
TERM = ("com.mitchellh.ghostty", "~/dev")


def test_keys_are_split_by_the_window_they_landed_in():
    counter = Counter(T0)
    counter.record(Activity.KEY, T0 + 1.1, EMACS)
    counter.record(Activity.KEY, T0 + 1.5, TERM)
    counter.record(Activity.KEY, T0 + 1.7, EMACS)
    counter.record(Activity.KEY, T0 + 9.0, EMACS)
    counter.record(Activity.POINTER, T0 + 9.5, TERM)

    [row] = counter.close_minutes(T0 + 60)

    assert (row.keys, row.key_seconds) == (4, 2)
    assert row.windows == (
        WindowRow(app_id="emacs", title="notes.org", keys=3, key_seconds=2),
        WindowRow(app_id="com.mitchellh.ghostty", title="~/dev", keys=1, key_seconds=1),
    )


def test_keys_without_a_window_count_only_toward_the_minute():
    counter = Counter(T0)
    counter.record(Activity.KEY, T0 + 1, EMACS)
    counter.record(Activity.KEY, T0 + 2)
    [row] = counter.close_minutes(T0 + 60)
    assert row.keys == 2
    assert row.windows == (WindowRow(app_id="emacs", title="notes.org", keys=1, key_seconds=1),)
