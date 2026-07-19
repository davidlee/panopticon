"""Compositor detection — resolve a ``--compositor`` choice to an adapter.

:func:`select_client` maps ``auto|sway|niri`` to a
(:class:`~panopticon.compositor.model.CompositorClient`, ``producer``)
pair. ``auto`` runs a **connect-validated** probe (SPEC-001 D7): for each set
socket var it attempts a real connect + handshake under a bounded timeout (F-5),
uses the one that connects, and prefers **niri** when both connect (DL-4). This
retires the RV-001 F-1 ``SWAYSOCK``-presence stand-in.

Adapter imports (``i3ipc`` for sway, the niri stack) are deferred into the
resolver so ``--help`` and arg parsing work on hosts without an IPC stack — no
compositor code loads on the parse path.
"""

from __future__ import annotations

import asyncio
import os

from panopticon.compositor.model import CompositorClient

AUTO = "auto"
SWAY = "sway"
NIRI = "niri"

NIRI_SOCKET_ENV = "NIRI_SOCKET"
SWAY_SOCKET_ENV = "SWAYSOCK"

# Bound the auto probe so a wedged compositor (socket accepts, handler hung)
# fails fast instead of stalling startup (F-5).
_PROBE_TIMEOUT = 2.0


def select_client(compositor: str) -> tuple[CompositorClient, str]:
    """Resolve ``compositor`` to a ``(client, producer)`` pair."""
    if compositor == SWAY:
        return _sway_client(), SWAY
    if compositor == NIRI:
        return _niri_client(), NIRI
    if compositor == AUTO:
        return _auto_select()
    raise ValueError(f"unknown compositor: {compositor!r}")


def _auto_select() -> tuple[CompositorClient, str]:
    """Connect-validated D7 resolution: probe niri first (DL-4), then sway.

    Only a *set* socket var is probed; the one that connects wins, niri ahead of
    sway when both do. Nothing reachable → raise, listing what was tried.
    """
    tried: list[str] = []

    niri_sock = os.environ.get(NIRI_SOCKET_ENV)
    if niri_sock:
        tried.append(f"{NIRI_SOCKET_ENV}={niri_sock}")
        if _probe_niri(niri_sock):
            return _niri_client(), NIRI

    sway_sock = os.environ.get(SWAY_SOCKET_ENV)
    if sway_sock:
        tried.append(f"{SWAY_SOCKET_ENV}={sway_sock}")
        if _probe_sway(sway_sock):
            return _sway_client(), SWAY

    detail = ", ".join(tried) if tried else f"neither {NIRI_SOCKET_ENV} nor {SWAY_SOCKET_ENV} set"
    raise RuntimeError(
        f"--compositor auto found no reachable compositor (tried: {detail}); "
        "pass --compositor sway|niri explicitly, or check the socket is live"
    )


def _probe_niri(sock_path: str) -> bool:
    """Connect-validate niri via the event-stream handshake (bounded, F-5)."""
    from panopticon.compositor.niri import protocol

    try:
        return asyncio.run(protocol.probe(sock_path, connect_timeout=_PROBE_TIMEOUT))
    except Exception:  # any connect/timeout/ack failure → not reachable
        return False


def _probe_sway(sock_path: str) -> bool:
    """Connect-validate sway via an i3ipc connect + subscribe round-trip.

    A real connect (retiring the ``SWAYSOCK``-presence stand-in), bounded so a
    wedged sway fails fast, torn down immediately — i3ipc exposes no public
    close, so we undo what ``connect()`` set up (R-3). Any failure → not
    reachable.
    """
    import i3ipc.aio

    async def _try() -> bool:
        conn = await asyncio.wait_for(
            i3ipc.aio.Connection(socket_path=sock_path).connect(), _PROBE_TIMEOUT
        )
        _close_i3ipc(conn)
        return True

    try:
        return asyncio.run(_try())
    except Exception:  # any connect/timeout failure → not reachable
        return False


def _close_i3ipc(conn: object) -> None:
    """Best-effort teardown of an i3ipc connection opened solely to probe.

    ``i3ipc.aio.Connection`` has no public close; ``connect()`` opens a command
    and a subscribe socket and registers a loop reader on the latter. Undo those
    so the probe leaks no fds. Guarded so an internals change never breaks the
    probe — the one-shot ``asyncio.run`` loop teardown is the backstop.
    """
    loop = getattr(conn, "_loop", None)
    sub_fd = getattr(conn, "_sub_fd", None)
    if loop is not None and sub_fd is not None:
        loop.remove_reader(sub_fd)
    for attr in ("_cmd_socket", "_sub_socket"):
        sock = getattr(conn, attr, None)
        if sock is not None:
            sock.close()


def _niri_client() -> CompositorClient:
    # Deferred: importing the adapter keeps the niri stack off the --help path.
    from panopticon.compositor.niri.session import NiriClient

    sock = os.environ.get(NIRI_SOCKET_ENV)
    if not sock:
        raise RuntimeError(
            f"--compositor niri requires ${NIRI_SOCKET_ENV}; it is not set"
        )
    return NiriClient(sock)


def _sway_client() -> CompositorClient:
    # Deferred: importing the adapter pulls in i3ipc; keep it out of the
    # arg-parsing / --help path.
    from panopticon.compositor.sway._i3ipc import I3ipcSwayClient

    return I3ipcSwayClient()
