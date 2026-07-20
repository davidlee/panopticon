# home-manager switch requires daemon-reload before restart (systemd-user)

After `home-manager switch`, `systemctl --user restart <unit>` can relaunch the
**stale in-memory ExecStart** — the *old* binary — even though `systemctl cat`
shows the new one. `NeedDaemonReload=no` is a **false negative** here, so nothing
warns you.

**Mechanism.** `switch` flips the unit *symlink* to the new Nix store fragment, but
systemd decides whether a reload is needed by comparing the loaded fragment's
mtime. Nix store files carry a fixed **1970 mtime** and are immutable, so the
retarget never trips systemd's mtime check: `systemctl cat` reads disk (new), the
*manager* still runs its cached memory copy (old). A plain `restart` then relaunches
the old ExecStart.

**Fix.** Always `systemctl --user daemon-reload` **before** `restart` after a HM
switch:

    systemctl --user daemon-reload && systemctl --user restart <unit>

**Where this bit us (SL-004).** The panopticon watcher unit's ExecStart was flipped
`panopticon-sway` → `panopticon-desktop`, but a bare restart kept relaunching the
old sway watcher (crash-looping on a niri host, still writing `raw/sway-*.jsonl`),
so `current/desktop.json` never appeared and host VH-1 looked blocked. `cat` said
desktop, the process was sway. daemon-reload + restart fixed it instantly.
See [[mem.fact.panopticon.niri-live-sway-dormant]].
