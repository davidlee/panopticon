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
| `capture-0.ndjson` | `umbriel 0.1.0` | `subscribe windows workspaces` stream: line 1 = startup `windows` full snapshot, line 2 = `workspaces` full snapshot (the immediate subscribe burst), then `windows` events for within-workspace focus cycling, title mutation, a window open (`kitty`), and geometry moves. Confirms: immediate burst on subscribe, full-snapshot-per-event (no deltas), per-workspace `focused` (two `focused:true` windows at once), `output:index` workspace ids (`DP-3:1`), `output` = DRM connector (`DP-3`). **Frame 4 has `#active==0`** — the transient empty-`active` case the D1 spike hinges on. |
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

## Absent captures (resolve at SL-005 /design)

- **Workspace switch** not captured — confirm it fires a `workspaces` event (the
  focused-workspace derivation depends on it). Window-focus-within-a-workspace
  fires a `windows` event, seen here.
- **`active` vs `focused` window-flag semantics** — `active` is absent in some
  frames; the projection uses the focused-workspace→focused-window join, not
  `active`. PHASE-02 session tests hand-author edge scenarios from this capture's
  vocabulary plus the design's event→mutation table (as SL-003 did).
