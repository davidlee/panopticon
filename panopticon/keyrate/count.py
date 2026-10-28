"""Pure keyrate core: classify input events, count them per second, roll up per minute.

No clock and no I/O: every time is an argument (wall-clock epoch seconds). The
event codes are the Linux input ABI (``linux/input-event-codes.h``), stable by
contract, so this module needs no ``evdev`` import.

Nothing here keeps a key code or a per-event timestamp: an event becomes one
increment of a per-second bucket and the code is dropped on the spot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

EV_KEY, EV_REL, EV_ABS = 0x01, 0x02, 0x03
KEY_A = 30
BTN_MISC, BTN_LEFT, BTN_TOOL_PEN, BTN_TOUCH, KEY_OK = 0x100, 0x110, 0x140, 0x14A, 0x160
REL_X = 0x00
BUS_VIRTUAL = 0x06
PRESS = 1

MODIFIERS = frozenset(
    {
        29, 97,  # KEY_LEFTCTRL, KEY_RIGHTCTRL
        42, 54,  # KEY_LEFTSHIFT, KEY_RIGHTSHIFT
        56, 100,  # KEY_LEFTALT, KEY_RIGHTALT
        125, 126,  # KEY_LEFTMETA, KEY_RIGHTMETA
        58,  # KEY_CAPSLOCK
    }
)  # fmt: skip

MINUTE = 60
PEAK_WINDOW = 5
LIVE_WINDOW = 60


class Activity(Enum):
    KEY = "key"
    POINTER = "pointer"


def classify(ev_type: int, code: int, value: int) -> Activity | None:
    """What one input event counts as, or ``None`` if it counts for nothing.

    A key is a press (not a release or autorepeat) of a non-modifier keyboard
    key. Pointer activity is any motion, wheel or absolute-axis event, or a
    button press.
    """
    if ev_type in (EV_REL, EV_ABS):
        return Activity.POINTER
    if ev_type != EV_KEY or value != PRESS:
        return None
    if code < BTN_MISC:
        return None if code in MODIFIERS else Activity.KEY
    if code < KEY_OK:
        return Activity.POINTER
    return None


def is_watched(capabilities: Mapping[int, Iterable[int]], bustype: int) -> bool:
    """Whether a device is a keyboard or a pointer you operate, from ``{ev_type: [codes]}``.

    Virtual-bus devices are uinput: software typing for you (a snippet
    expander), not you.
    """
    if bustype == BUS_VIRTUAL:
        return False
    keys = set(capabilities.get(EV_KEY, ()))
    is_keyboard = KEY_A in keys
    is_mouse = REL_X in set(capabilities.get(EV_REL, ()))
    is_touch_or_pen = bool(keys & {BTN_TOUCH, BTN_TOOL_PEN})
    return is_keyboard or is_mouse or is_touch_or_pen


# The focused window a key landed in: (app_id, title).
Window = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class WindowRow:
    """A minute's keys that landed in one window. ``key_seconds`` overlap across windows."""

    app_id: str
    title: str | None
    keys: int
    key_seconds: int


@dataclass(frozen=True, slots=True)
class MinuteRow:
    """One closed minute. ``start`` is its epoch second; counts cover ``[start, start+60)``.

    ``windows`` attributes the keys to the focused window, in order of first key;
    keys with no known window count only toward the minute.
    """

    start: int
    keys: int
    key_seconds: int
    pointer_seconds: int
    peak_5s_cpm: int
    windows: tuple[WindowRow, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The live rate at one instant, for a bar."""

    cpm_5s: int
    cpm_60s: int
    pointer_seconds_60s: int


@dataclass(slots=True)
class _Second:
    keys: int = 0
    pointer: bool = False
    window_keys: dict[Window, int] = field(default_factory=dict)


class Counter:
    """Per-second buckets, closed into :class:`MinuteRow` s on wall-clock minutes.

    Retains at most the open minute and the last :data:`LIVE_WINDOW` seconds.
    """

    def __init__(self, now: float) -> None:
        self._open_minute = _minute_of(int(now))
        self._seconds: dict[int, _Second] = {}

    def record(self, activity: Activity, t: float, window: Window | None = None) -> None:
        second = int(t)
        if second < self._open_minute:
            return
        bucket = self._seconds.setdefault(second, _Second())
        if activity is Activity.KEY:
            bucket.keys += 1
            if window is not None:
                bucket.window_keys[window] = bucket.window_keys.get(window, 0) + 1
        else:
            bucket.pointer = True

    def close_minutes(self, now: float) -> list[MinuteRow]:
        """Rows for every minute that ended by ``now`` and saw activity, oldest first."""
        current = _minute_of(int(now))
        closing = sorted({_minute_of(s) for s in self._seconds if s < current})
        rows = [self._row(m) for m in closing if m >= self._open_minute]
        self._open_minute = max(self._open_minute, current)
        self._prune(int(now))
        return rows

    def snapshot(self, now: float) -> Snapshot:
        second = int(now)
        self._prune(second)
        return Snapshot(
            cpm_5s=self._keys_since(second - PEAK_WINDOW) * MINUTE // PEAK_WINDOW,
            cpm_60s=self._keys_since(second - LIVE_WINDOW) * MINUTE // LIVE_WINDOW,
            pointer_seconds_60s=sum(
                b.pointer for s, b in self._seconds.items() if s > second - LIVE_WINDOW
            ),
        )

    def retained_seconds(self) -> int:
        return len(self._seconds)

    def _row(self, minute: int) -> MinuteRow:
        seconds = {s: b for s, b in self._seconds.items() if minute <= s < minute + MINUTE}
        keyed = {s: b.keys for s, b in seconds.items() if b.keys}
        peak = max(
            (sum(n for k, n in keyed.items() if s <= k < s + PEAK_WINDOW) for s in keyed),
            default=0,
        )
        return MinuteRow(
            start=minute,
            keys=sum(keyed.values()),
            key_seconds=len(keyed),
            pointer_seconds=sum(b.pointer for b in seconds.values()),
            peak_5s_cpm=peak * MINUTE // PEAK_WINDOW,
            windows=_window_rows(seconds.values()),
        )

    def _keys_since(self, after: int) -> int:
        return sum(b.keys for s, b in self._seconds.items() if s > after)

    def _prune(self, second: int) -> None:
        keep_from = min(self._open_minute, second - LIVE_WINDOW)
        for s in [s for s in self._seconds if s < keep_from]:
            del self._seconds[s]


def _window_rows(seconds: Iterable[_Second]) -> tuple[WindowRow, ...]:
    keys: dict[Window, int] = {}
    key_seconds: dict[Window, int] = {}
    for bucket in seconds:
        for window, n in bucket.window_keys.items():
            keys[window] = keys.get(window, 0) + n
            key_seconds[window] = key_seconds.get(window, 0) + 1
    return tuple(
        WindowRow(app, title, keys[(app, title)], key_seconds[(app, title)]) for app, title in keys
    )


def _minute_of(second: int) -> int:
    return second - second % MINUTE
