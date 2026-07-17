"""Neutral event encoder — the sole injector of ``source`` and ``producer``.

:func:`encode` maps a :class:`~panopticon.compositor.model.DesktopObservation`
to a schema-v1 :class:`~panopticon.schema.Event` stamped ``source:"desktop"``
plus the adapter's ``producer``. The observation's ``fields`` (already
carrying ``window_id`` where relevant) pass through verbatim (F8). No
other module writes ``source`` or ``producer`` (INV-2), so adding a second
adapter (SL-003) is a new ``producer`` value, not a schema reshape.
"""

from __future__ import annotations

from panopticon.compositor.model import DesktopObservation
from panopticon.schema import Event, make_event

SOURCE = "desktop"


def encode(obs: DesktopObservation, producer: str) -> Event:
    """Encode ``obs`` as a ``source:"desktop"`` event carrying ``producer``."""
    return make_event(SOURCE, obs.event, producer=producer, **obs.fields)
