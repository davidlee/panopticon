# Brief: Shared compositor abstraction for Sway and Niri

## Objective

Refactor Panopticon’s desktop watcher so Sway and Niri are supported behind a shared compositor-neutral abstraction.

The implementation should preserve current Sway behaviour and wire compatibility while introducing a clean path for Niri support. The resulting architecture must treat Sway and Niri as producers of normalized desktop-attention observations rather than exposing their native IPC models to the rest of Panopticon.

Repository:

```text
davidlee/panopticon
```

## Current state

Panopticon currently has a Sway-specific watcher built around:

* `panopticon-sway`
* `i3ipc`
* `AsyncSession.get_tree()`
* raw Sway IPC events
* `FocusState`
* `current/sway.json`
* `raw/sway-YYYY-MM-DD.jsonl`
* schema events with `source: "sway"`
* Sway-specific field names such as `con_id`

The existing abstraction boundary is too low-level.

`runner.py` accepts a protocol, but that protocol still encodes Sway’s model:

```python
class AsyncSession(Protocol):
    def events(self) -> AsyncIterator[IpcEvent]: ...
    async def get_tree(self) -> dict[str, Any]: ...
```

A Niri adapter should not have to synthesize a fake Sway tree or expose raw Niri IPC details to shared code.

## Architectural direction

Introduce a compositor-neutral desktop watcher layer.

Each compositor adapter must:

1. connect to its native IPC;
2. maintain whatever native state projection it requires;
3. normalize native state and events into shared desktop observations;
4. expose those observations to a shared runner.

The shared runner must own:

* reconnect and backoff;
* logging;
* snapshot persistence;
* normalized event persistence;
* current-state persistence;
* compositor-independent lifecycle events.

The shared layer must not know about:

* Sway trees;
* Niri event variants;
* container ancestry;
* Niri columns;
* compositor-specific socket protocols.

## Proposed shared model

Use a model along these lines, adjusting details where implementation evidence warrants it:

```python
@dataclass(frozen=True, slots=True)
class WindowRef:
    window_id: int | str | None = None
    app_id: str | None = None
    pid: int | None = None
    title: str | None = None
    workspace: str | None = None
    output: str | None = None


@dataclass(frozen=True, slots=True)
class DesktopState:
    focused_window: WindowRef | None = None


@dataclass(frozen=True, slots=True)
class DesktopObservation:
    kind: str
    window: WindowRef | None = None
    previous: WindowRef | None = None
    fields: Mapping[str, object] = field(default_factory=dict)


class CompositorSession(Protocol):
    async def initial_state(self) -> DesktopState: ...

    def observations(self) -> AsyncIterator[DesktopObservation]: ...


class CompositorClient(Protocol):
    name: str

    def session(
        self,
    ) -> AbstractAsyncContextManager[CompositorSession]: ...
```

The exact types are not prescribed, but the boundary is:

```text
native compositor IPC
        ↓
compositor-specific adapter
        ↓
normalized desktop observations
        ↓
shared runner and event encoder
```

Do not make raw native IPC events part of the shared API.

## Target package structure

Aim for a structure approximately like:

```text
panopticon/
  compositor/
    model.py
    runner.py
    events.py
    detect.py

    sway/
      client.py
      normalize.py
      tree.py

    niri/
      client.py
      protocol.py
      projection.py
      normalize.py

  desktop_watcher/
    __main__.py
```

Do not follow this mechanically if the existing package layout suggests a cleaner arrangement. Preserve the separation of concerns.

## Sway adapter responsibilities

Move all Sway-specific logic behind the Sway adapter, including:

* `get_tree`;
* tree traversal;
* focused leaf selection;
* ancestor workspace/output lookup;
* `app_id` fallback through XWayland window properties;
* interpretation of Sway window events;
* interpretation of Sway workspace events;
* Sway container IDs;
* raw `i3ipc` payload handling.

Existing functions such as these should become Sway-private:

```text
app_id_from_container
find_focused
ancestor_name_of_type
focus_state_from_tree
```

The Sway adapter should emit normalized observations containing complete state where practical.

In particular, fix or explicitly account for the current behaviour where a window focus event inherits workspace and output from previous state rather than deriving them from the newly focused window. Do not silently preserve an incorrect association merely for implementation convenience.

## Niri adapter responsibilities

Implement the Niri adapter using Niri’s JSON IPC socket.

Prefer direct JSON socket communication from Python rather than introducing a Rust sidecar solely to consume `niri-ipc`.

The adapter should maintain a local projection sufficient for Panopticon:

```text
windows_by_id
workspaces_by_id
focused_window_id
active_workspace_by_output
```

The projection should consume:

* Niri’s initial state events;
* subsequent incremental events;
* window creation, change and close;
* focus changes;
* workspace changes;
* output associations where available.

The adapter should emit a normalized initial snapshot once sufficient initial state has been received, then emit normalized observations for relevant changes.

Do not attempt to fabricate Sway concepts in Niri:

* no fake container tree;
* no fake nested split ancestry;
* no fake marks;
* no fake binding events.

Niri-specific capabilities may be retained as optional metadata, but they must not contaminate the core shared model.

## Normalized event semantics

The shared semantic events should represent desktop behaviour, not compositor implementation.

Candidate normalized events include:

```text
snapshot
window_focus
window_title
window_open
window_close
window_move
window_fullscreen_mode
window_urgent
workspace_focus
workspace_urgent
compositor_disconnected
compositor_reconnected
```

Review the current segmentizer and consumers before finalizing this list.

Only introduce normalized events that are either:

* already consumed;
* useful for current Panopticon behaviour;
* clearly necessary for parity across Sway and Niri.

Avoid carrying every native compositor event through merely because it exists.

## Schema and compatibility

The desired end state is compositor-neutral:

```json
{
  "source": "desktop",
  "producer": "sway",
  "event": "window_focus",
  "window_id": 123
}
```

and:

```json
{
  "source": "desktop",
  "producer": "niri",
  "event": "window_focus",
  "window_id": 42
}
```

However, do not combine architectural extraction, Niri support and a hard schema migration unless necessary.

Plan a compatibility transition.

Likely compatibility measures:

* accept both `source: "sway"` and `source: "desktop"` in downstream processing;
* temporarily emit `con_id` alongside `window_id`;
* continue writing `current/sway.json` while introducing `current/desktop.json`;
* preserve existing Sway raw files until consumers have migrated;
* keep `panopticon-sway` as a compatibility entrypoint.

Determine which compatibility layers are actually required by inspecting:

* segmentizer inputs;
* tests;
* SATAN consumers;
* Home Manager units;
* scripts;
* documentation;
* retention rules.

Do not guess.

## CLI direction

Introduce a shared executable:

```console
panopticon-desktop --compositor auto
panopticon-desktop --compositor sway
panopticon-desktop --compositor niri
```

Auto-detection should be simple:

```text
NIRI_SOCKET present → niri
SWAYSOCK present → sway
otherwise → fail clearly
```

Keep:

```console
panopticon-sway
```

as a compatibility wrapper during migration.

Consider:

```console
panopticon-niri
```

only if it materially simplifies Home Manager or service configuration.

## Constraints

### Preserve existing behaviour

The first architectural slice must preserve Sway output closely enough that existing fixtures and consumers continue to work.

Where behaviour changes, document why.

### Keep normalization pure

Native event decoding and projection updates should be unit-testable without a live compositor.

Prefer pure functions for:

* raw payload decoding;
* state transitions;
* observation construction;
* normalized event encoding.

### Avoid false unification

Do not design the abstraction around the union of all Sway and Niri capabilities.

The shared model should contain concepts Panopticon needs:

```text
focused window
application identity
title
workspace
output
relevant transitions
```

Compositor-specific details belong in adapter metadata or nowhere.

### Avoid premature generality

This is a two-compositor abstraction, not a universal Wayland compositor SDK.

Do not add plugin systems, dynamic registration or elaborate capability negotiation unless current requirements demonstrate a need.

### Preserve privacy properties

The refactor must not expand capture into:

* keystrokes;
* clipboard contents;
* screenshots;
* unrestricted window metadata beyond existing policy;
* arbitrary native IPC dumps.

Review `docs/privacy.md` and existing schema constraints.

## Required investigation

Before proposing the implementation plan, inspect at least:

```text
panopticon/sway_watcher/
panopticon/segmentizer/
panopticon/schema.py
panopticon/store.py
tests/
docs/schema.md
docs/privacy.md
pyproject.toml
flake.nix or equivalent Nix packaging
Home Manager/service definitions if present or referenced
SATAN integration points if available
```

Identify:

* every place that assumes `source == "sway"`;
* every use of `con_id`;
* every read or write of `current/sway.json`;
* every filename convention involving `sway-`;
* every test fixture coupled to Sway payloads;
* every downstream consumer that expects the current schema;
* service and package entrypoints;
* any assumptions about process lifetime or reconnect behaviour.

Also inspect current Niri IPC documentation or protocol definitions sufficiently to confirm:

* socket framing;
* initial event-stream behaviour;
* relevant event variants;
* ID types;
* workspace/output associations;
* reconnect behaviour;
* compatibility considerations.

## Implementation slicing

Produce an implementation plan divided into small, reviewable slices.

The expected direction is:

### Slice 1: Shared domain model and runner

* introduce compositor-neutral state and observation types;
* extract shared reconnect and persistence loop;
* introduce shared normalized event encoding;
* retain current Sway output through compatibility mapping.

### Slice 2: Move Sway behind the adapter

* relocate tree and raw IPC interpretation;
* implement the shared session contract;
* preserve existing Sway fixtures;
* add equivalence or golden tests proving behaviour remains stable.

### Slice 3: Shared CLI and detection

* add `panopticon-desktop`;
* add explicit compositor selection;
* add environment-based auto-detection;
* retain `panopticon-sway` wrapper;
* update packaging and services.

### Slice 4: Niri protocol and projection

* implement socket connection and framing;
* model initial state accumulation;
* implement projection transitions;
* test with recorded Niri event fixtures.

### Slice 5: Niri normalization

* emit normalized snapshots and events;
* ensure focus, title, workspace and output behaviour is correct;
* add reconnect tests;
* add integration-level fixture tests.

### Slice 6: Storage and schema migration

* migrate toward `source: desktop`;
* introduce `producer`;
* introduce `window_id`;
* update segmentizer and consumers;
* retain or remove compatibility fields based on verified downstream state.

### Slice 7: Documentation and operational migration

* update README architecture;
* update schema documentation;
* update privacy documentation if required;
* update Home Manager/systemd configuration;
* document Sway-to-Niri switching;
* remove obsolete aliases only when safe.

Revise these slices if repository evidence supports a better dependency order.

## Testing expectations

The plan should include tests for:

### Shared runner

* initial snapshot;
* observation persistence;
* current-state persistence;
* disconnect event;
* reconnect event;
* exponential backoff;
* cancellation;
* source/producer selection.

### Sway

* focused-window extraction from trees;
* native Wayland `app_id`;
* XWayland class fallback;
* window focus;
* title change;
* window open and close;
* workspace focus;
* workspace/output correctness;
* reconnect reconciliation;
* compatibility event output.

### Niri

* socket framing;
* initial state accumulation;
* window projection;
* workspace projection;
* focus transitions;
* title changes;
* window close while focused;
* output/workspace reassignment;
* incomplete or out-of-order state where protocol permits;
* event-stream EOF and reconnect;
* unknown additive event fields;
* unknown event variants handled without crashing where appropriate.

### Cross-compositor contract

Given equivalent desktop transitions, Sway and Niri fixtures should produce equivalent normalized observations except for:

```text
producer
native window ID
optional compositor-specific metadata
```

## Deliverable

Do not begin implementation immediately.

First produce a grounded implementation plan containing:

1. a concise account of the current architecture;
2. the specific coupling points that prevent Niri support;
3. the proposed shared interfaces and ownership boundaries;
4. a file-by-file change plan;
5. migration and compatibility risks;
6. test strategy;
7. implementation slices in dependency order;
8. unresolved decisions requiring explicit choice;
9. any places where this brief is contradicted by repository evidence.

For each proposed slice, include:

```text
goal
files affected
public behaviour changed
compatibility implications
tests added or changed
acceptance criteria
dependencies
```

Prefer the smallest coherent refactor that makes Niri a first-class adapter without reducing Sway reliability.
