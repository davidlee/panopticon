# IDE-003: Host config file, with redaction settings pushed to the extension over the native port

<!-- Backlog item body — context, detail, links. The structured, queried fields
     live in the sister `backlog-NNN.toml`; this prose is free-form and is never
     structurally parsed (the storage rule). -->

Raised 2026-10-01 while fixing ISS-003.

## Problem

panopticon has no config file. The firefox host's only knob,
`record_file_urls`, is a CLI flag — and Firefox launches the native host
from its manifest without arguments, so it is unreachable in practice.
Redaction policy (ISS-003's per-host identity params, sensitive schemes) is
baked twice: in the host and in the extension, kept equal by a parity test.

## Shape

- A host config file, e.g. `$XDG_CONFIG_HOME/panopticon/firefox-host.toml`
  (`record_file_urls`, identity-param map, …), loaded and validated at start.
- The host pushes the redaction settings to the extension over the native
  port on connect (the port is bidirectional; today traffic is one-way). The
  extension keeps a baked default until the push arrives and re-receives it
  on reconnect (event page is non-persistent).
- Single source of truth; retires the ISS-003 parity test.

Trigger: a second setting worth configuring, or wanting to tune the
identity-param map without a rebuild.
