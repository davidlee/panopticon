"""Event schema (v=1).

Every JSONL event is one JSON object per line with top-level fields
``v``, ``ts``, ``source``, ``event``, plus event-specific fields.
Consumers should skip events whose ``v`` they don't understand.
"""

from __future__ import annotations

SCHEMA_VERSION = 1
