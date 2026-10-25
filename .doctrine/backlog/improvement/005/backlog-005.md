# IMP-005: keyrate: key and pointer counts per minute, live socket, cutover from wpm-daemon

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-10-26: record keyboard activity as a time series (chars/min)
without keylogging, portably across compositors, so SATAN can tell idleness
from focus. Bonus: a live CPM feed for a bar, built separately.

## Today (found while scoping)

- `wpm-daemon.service` runs `~/.config/waybar/wpm-status.py --daemon`
  (defined in `~/flakes/features/desktop/sway.nix:106-150`, with
  `wpm-archive.timer` rolling each day's file into hourly rows at 04:00).
- It reads evdev directly, counts every `EV_KEY` press including modifiers,
  and appends one row per minute to
  `~/.local/state/satan/log/wpm/YYYY-MM-DD.tsv`:
  `<iso8601_local> <keys> <peak_5s_wpm> <active_seconds>`.
  It also writes a 1 Hz Waybar snapshot to `$XDG_RUNTIME_DIR/wpm.json`;
  nothing reads it since Waybar went.
- SATAN consumes the TSV in `satan/satan-sensor-wpm.el`: over the last 10
  minutes, `active_seconds` > 300 → `typing_active`, < 30 → `typing_idle`.
  Keys only, so reading looks the same as being away.
- Access comes from the user being in the `input` group (RSK-002). Dictation
  does not depend on that group (compositor bindings → signals; output via
  `wtype`).

## Mechanism (decided)

evdev is the only source that is compositor-independent and gives a rate.
Rejected: Wayland `ext-idle-notify-v1` (binary idle/active, no rate);
`/proc/interrupts` (USB interrupts count per controller, not per keyboard);
compositor IPC (none expose key counts); keyboard firmware (misses the
laptop keyboard).

## Design sketch

```
/dev/input/event*  (keyboards + pointers, read-only)
        │
        ▼
 shell: discover + hotplug, read events ──▶ pure core
                                             │  key press (not modifier,
                                             │  not autorepeat) → keys++
                                             │  pointer motion/button/wheel
                                             │  → pointer++
                                             │  code discarded on the spot
                                             ▼
                          ┌──────────────────┼────────────────────┐
                          ▼                  ▼                    ▼
                  raw/keyrate-*      legacy TSV (step 1–2)   keyrate.sock
                  1 row / minute     satan/log/wpm/*.tsv     1 JSON line / s
                                                             per client
```

- **Pure core** (no clock, no I/O; time is an input): classify an event
  (key / modifier / repeat / pointer / other), accumulate per-second counts,
  close a minute into a row, compute the 1 Hz snapshot
  (`cpm_5s`, `cpm_60s`, `pointer_60s`). Bucket boundaries on wall-clock
  minutes, not on the first event.
- **Shell**: device discovery (keyboard = has `KEY_A`; pointer = has
  `REL_X` or `BTN_LEFT`), hotplug rescan, selector loop, the writers, the
  socket server.
- **Minute row**: `ts` (minute start), `keys`, `pointer`, `active_seconds`
  (seconds with any key press), `peak_5s_cpm`. Schema in `docs/schema.md`.
  Minutes with no activity are not written.
- **Legacy TSV**: same path and four columns as today, so SATAN needs no
  change. Behaviour change: modifiers no longer counted, so `keys` and
  `peak_5s_wpm` read ~20–30% lower; `active_seconds` (what the sensor uses)
  barely moves.
- **Socket**: `$XDG_RUNTIME_DIR/panopticon/keyrate.sock`, mode 0600. Each
  client gets one JSON line per second; a bar reads it with
  `socat -u UNIX-CONNECT:… -` (eww `deflisten`, Waybar `exec`). Replaces
  `wpm.json`.
- **Never emitted, anywhere**: key codes, and timestamps per event.
  Inter-key timing is a side channel (it leaks passwords and text), so
  persistence is per-minute and the live feed is per-second.
- **Unit**: user service, like `panopticon-sway`. Python, reusing the
  store, settings and unit conventions; the old script's core is ~150
  lines.
- **Tests**: TDD on the pure core; writers and socket against fakes; no
  real `/dev/input`.
- **Docs**: `docs/privacy.md` — what is counted, what is never recorded,
  and the dependence on `input` group membership (RSK-002).

## Steps

Nothing breaks at any step: SATAN keeps reading the TSV until step 2 lands.

1. **panopticon**: `panopticon-keyrate` with the raw stream, legacy TSV and
   socket. **`~/flakes`**: replace `wpm-daemon` with it; keep `wpm-archive`
   (it only rewrites files).
2. **SATAN**: `satan-sensor-wpm.el` reads `raw/keyrate-*` and adds a reading
   state (few keys, pointer activity).
3. **Cleanup**: drop the legacy TSV writer from panopticon; drop
   `wpm-archive` and `wpm-status.py` from `~/flakes`.

Later, optional: the segmentizer joins minute rows with focus segments
("typing in Emacs", "reading in Firefox").
