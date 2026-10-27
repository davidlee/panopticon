# ISS-004: Extension reconnect backoff resets on connectNative, so a crashing host respawns every second

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Found in SL-010 design §2 (pre-existing); audit.md § Out of scope.

## Problem

`connect()` in `firefox-extension/background.js` set `reconnectDelay` back to
the minimum as soon as `browser.runtime.connectNative` returned. That call
returns before the host has proven it runs, so a host that dies at start
(bad install, Python error) disconnects at once and is respawned every 1 s,
forever: the exponential backoff (1 s → 30 s) never engages.

## Fix

Reset the backoff on disconnect only if the connection stayed up at least
`RECONNECT_STABLE_MS` (10 s). A host that dies sooner keeps doubling toward
the 30 s cap.
