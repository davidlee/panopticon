# Niri golden-capture fixtures — provenance

Live host captures of the niri IPC event stream over `$NIRI_SOCKET`, committed
**byte-verbatim** so replay through `NiriProjection.apply` exercises the real
wire format (SL-003 design §9, EX-4). The `=26.4.0` pin is **wire-format
provenance recorded here**, NOT a package dependency — Niri is parsed with stdlib
`json` and carries no python runtime dep (SPEC-001 D3).

| fixture | niri --version | contents |
|---|---|---|
| `capture-0.ndjson` | `niri 26.4.0` | startup burst (ack, `WorkspacesChanged`, `WindowsChanged`, `KeyboardLayoutsChanged`, `OverviewOpenedOrClosed`, `ConfigLoaded`, `CastsChanged`) + within-workspace focus cycling (`WorkspaceActiveWindowChanged`→`WindowFocusChanged`, 106→104→106) + a `WindowOpenedOrChanged` title mutate. The clean DL-6 baseline; confirms ASM-1 (`output: "DP-3"`). |

## Capture protocol

Recorded from the host (outside the build jail — niri is unreachable in-jail):

```
python -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); \
  s.connect(__import__("os").environ["NIRI_SOCKET"]); \
  s.sendall(b"\"EventStream\"\n"); f=s.makefile(); \
  [sys.stdout.write(f.readline()) for _ in range(200)]' | tee niri-golden.ndjson
```

Line 0 is the `{"Ok":"Handled"}` ack; every subsequent line is one JSON event.

## Absent captures (SL-003 §9)

Captures 1 (empty-workspace switch) and 2 (overview flap) described in the design
were not preserved into the repo and cannot be re-captured in-jail. PHASE-02's
session tests hand-author their scenarios from this capture's event vocabulary
plus the design's event→mutation table.
