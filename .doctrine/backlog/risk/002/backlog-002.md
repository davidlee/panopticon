# RSK-002: user in input group: any process running as david can read raw keystrokes

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-10-26 while scoping IMP-005.

## Evidence

- `id` shows the user in `input` (gid 174), so `/dev/input/event*` is
  readable by every process running as david: an npm postinstall, an agent,
  a stray binary. That is full keylogging capability. Not checked: whether
  the bubblewrap jails bind-mount `/dev/input`.
- Holding `/dev/input/event*` open on 2026-10-26: Umbriel, the WPM daemon
  (`wpm-status.py`, later `panopticon-keyrate`, IMP-005), and
  `vicinae-input-server`.
- Dictation does not depend on the group: Umbriel binds F9 / XF86Tools /
  XF86Launch5 to `dictate`, which signals `dictate.service`; output goes
  through `wtype`.

## Inference (unverified)

- Umbriel probably gets its devices through logind / libseat and does not
  need the group.
- `vicinae-input-server` probably does need it.

## Mitigation shape

Remove the user from `input`. Give each remaining reader access on its own:
for `panopticon-keyrate`, a system service with `DynamicUser`,
`SupplementaryGroups=input`, `PrivateNetwork`, `ProtectSystem=strict`, that
writes counts where the user can read them. Vicinae needs its own answer
(or the feature it serves goes).
