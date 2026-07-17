"""Compositor detection — resolve a ``--compositor`` choice to an adapter.

:func:`select_client` maps ``auto|sway|niri`` to a
(:class:`~panopticon.compositor.model.CompositorClient`, ``producer``)
pair. SL-002 ships the Sway path and a detection *seam*, not the full D7
logic: ``niri`` (and ``auto`` when Sway is not reachable) raise
``NotImplementedError`` pointing at SL-003 — a seam, not a lie (DD10).
The both-set / full connect-validated liveness resolution lands with the
second adapter (SL-003).

The i3ipc import is deferred into the resolver so ``--help`` and arg
parsing work on hosts without the IPC stack.
"""

from __future__ import annotations

import os

from panopticon.compositor.model import CompositorClient

AUTO = "auto"
SWAY = "sway"
NIRI = "niri"

_SL003 = "the niri adapter and full auto-detection land in SL-003"


def select_client(compositor: str) -> tuple[CompositorClient, str]:
    """Resolve ``compositor`` to a ``(client, producer)`` pair."""
    if compositor == SWAY:
        return _sway_client(), SWAY
    if compositor == NIRI:
        raise NotImplementedError(f"--compositor niri: {_SL003}")
    if compositor == AUTO:
        if _sway_reachable():
            return _sway_client(), SWAY
        raise NotImplementedError(
            f"--compositor auto found no Sway socket; {_SL003} "
            "(pass --compositor sway explicitly for now)"
        )
    raise ValueError(f"unknown compositor: {compositor!r}")


def _sway_reachable() -> bool:
    """SL-002 connect-precondition: Sway exports ``SWAYSOCK``.

    A stand-in for the SL-003 connect-validated probe — enough to pick
    the Sway adapter when it is the only one that exists.
    """
    return bool(os.environ.get("SWAYSOCK"))


def _sway_client() -> CompositorClient:
    # Deferred: importing the adapter pulls in i3ipc; keep it out of the
    # arg-parsing / --help path.
    from panopticon.compositor.sway._i3ipc import I3ipcSwayClient

    return I3ipcSwayClient()
