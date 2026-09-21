# Umbriel golden-capture fixtures — provenance

Live host capture of the umbriel IPC event stream over the umbriel unix socket
(`$UMBRIEL_SOCKET`, else `$XDG_RUNTIME_DIR/umbriel-$WAYLAND_DISPLAY.sock`),
committed **byte-verbatim** so replay through the umbriel projection exercises the
real wire format (SL-005). Umbriel is parsed with stdlib `json` and carries no
python runtime dep (mirrors SPEC-001 D3 / the niri fixture). The captured umbriel
build is the **wire-format provenance**, NOT a package dependency — record the
`umbriel --version` here when re-capturing.

| fixture | umbriel --version | contents |
|---|---|---|
| `capture-0.ndjson` | `umbriel 0.1.0` | `subscribe windows workspaces` stream: line 1 = startup `windows` full snapshot, line 2 = `workspaces` full snapshot (the immediate subscribe burst), then `windows` events for within-workspace focus cycling, title mutation, a window open (`kitty`), and geometry moves. Confirms: immediate burst on subscribe, full-snapshot-per-event (no deltas), per-workspace `focused` (two `focused:true` windows at once), `output:opaque-id` workspace ids (`DP-3:1`; the suffix is an internal id, NOT the display index — `DP-3:17` has `index:2`), `output` = DRM connector (`DP-3`). **Frame 4 has `#active==0`** — the transient empty-`active` case the D1 spike hinges on. |
| `capture-1.ndjson` | `umbriel 0.1.0` | D1 spike: cross-workspace focus bounce (`window-focus:<id>` between `DP-3:1` and `DP-3:17`). Shows the **`windows`-before-`workspaces` ordering** on every cross-workspace jump (frames 3→4, 5→6, 8→9, 10→11) — the reason a focused-workspace join lags one frame and the adapter derives focus from the window `active` flag instead. See `slice/005/notes.md` §D1 spike. |

## Capture protocol

Recorded from the host (outside the build jail — umbriel is unreachable in-jail):

```
python -c 'import os,socket,sys; \
  p=os.environ.get("UMBRIEL_SOCKET") or f"{os.environ[\"XDG_RUNTIME_DIR\"]}/umbriel-{os.environ[\"WAYLAND_DISPLAY\"]}.sock"; \
  s=socket.socket(socket.AF_UNIX); s.connect(p); \
  s.sendall(b"{\"cmd\":\"subscribe\",\"events\":[\"windows\",\"workspaces\"]}\n"); \
  f=s.makefile(); [sys.stdout.write(f.readline()) for _ in range(200)]' | tee umbriel-golden.ndjson
```

Unlike niri there is **no ack line** — the stream opens directly with the
`windows` then `workspaces` full snapshots. Every line is one
`{"event":"<family>","data":[…]}` object; identical consecutive payloads are
coalesced by umbriel.

## Focus model — settled by the D1 spike (see `slice/005/notes.md` §D1, design DL-4)

The pre-capture guess (a focused-workspace→focused-window join as the *primary*
focus rule) was **reversed by the spike** and these captures:

- **`active` is the seat keyboard focus** (0-or-1 globally, verified never >1) and
  updates in-band on the `windows` event — it is the **primary** focus signal
  (Tier 1). `focused` is *per-workspace* (multiple true at once), not a global
  signal. Its transient empties (`capture-0` frame 4, `#active==0`) are covered by
  a pure Tier-2 fallback (focused window on the focused workspace), no prior state.
- **Cross-workspace switches DO fire a `workspaces` event**, but `capture-1` shows
  the `windows` event *precedes* it every time. The projection retains the last
  `workspaces` snapshot, so a switch onto a **pre-existing** workspace (every case in
  these captures) resolves its label immediately — no lag. The lag only bites a
  *genuinely new* workspace not yet in any snapshot; the composite id's suffix is an
  **opaque internal id, not the display index** (`DP-3:17` has `index:2`, `name:"2"`),
  so no label can be read from it — the session coherence-holds until the entry lands
  (design §5.2 `_locate` / §5.4). A pure workspace-switch with no focus change was not
  isolated, but the bounce in `capture-1` exercises the `workspaces`-event firing.

Edge scenarios the captures cannot force on demand (partial burst, burst-completion
timeout, live coherence hold on a new-workspace windows-before-workspaces sequence,
reconnect, scratchpad focus/active, geometry-only-no-emit) are hand-authored in
PHASE-01/02 from this vocabulary plus the design's event→mutation table (as SL-003
did). **Layer-surface / overview focus** is the one edge PHASE-01 tries to capture
**live** (host access) — to settle whether per-window `focused` persists on the last
tiled window while focus rests on a layer surface (design §5.5 / RV-005.3); if that
capture is inconclusive or skipped, the resulting Tier-2 over-count stands as an
accepted, documented limitation.
