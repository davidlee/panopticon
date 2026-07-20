# Doctrine id-allocation needs DOCTRINE_RESERVATION_FALLBACK=1 in the jail

Any doctrine verb that **mints a new id** — `review new`, `backlog new`,
`revision new`, `slice new`, `memory record`, `rec new` — first reserves the id
against the remote origin. In the nixos bubblewrap jail (`/workspace/*`), git's
ssh transport is a stub (`git-ssh-disabled`), so the reservation fetch dies with:

```
error: reach=auto: reservation remote origin unreachable and local fallback declined.
  ... fatal: cannot exec '/nix/store/…-git-ssh-disabled': No such file or directory
```

**Fix:** allocate locally — `DOCTRINE_RESERVATION_FALLBACK=1 doctrine <verb> …`
(or set `[reservation] allow-local-fallback=true`). The command prints
`reservation reach degraded to local` and proceeds. Only the *allocating* verb
needs it; downstream verbs (`review raise/dispose/verify`, `slice selector`,
`record-delta`) do not.

Local allocation is correct and safe for single-agent work in the jail — ids are
minted from the local ref namespace. It only matters if concurrent agents on
different hosts race the same namespace, which this environment does not.

Related: [[mem.fact.nix.hm-user-service-daemon-reload]] (the sibling
jail/host footgun).
