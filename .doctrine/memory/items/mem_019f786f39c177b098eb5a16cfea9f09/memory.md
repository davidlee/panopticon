# i3ipc aio.Connection has no public close — probe teardown

`i3ipc.aio.Connection` exposes no public close/disconnect. `connect()` opens two
blocking sockets (`_cmd_socket`, `_sub_socket`) and registers a loop reader
(`loop.add_reader(_sub_fd, …)`). Code that connects only to *probe* reachability
(e.g. `detect._probe_sway`, SL-003) must undo exactly those or it leaks fds:

    loop.remove_reader(conn._sub_fd)
    conn._cmd_socket.close()
    conn._sub_socket.close()

Reach in via guarded `getattr` (private attrs — an i3ipc upgrade may rename
them); the one-shot `asyncio.run` loop teardown is the backstop if they move.
Bound the probe with `asyncio.wait_for(Connection(...).connect(), timeout)` — the
blocking `socket.connect()` returns fast, but the `subscribe()` round-trip inside
`connect()` is what hangs on a wedged compositor.
