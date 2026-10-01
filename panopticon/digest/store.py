"""Per-SHA stage records beside the content store (design §5.3, D12).

Layout under ``root`` (``<state>/digest``), sharded like ``content/``::

    <sha[:2]>/<sha>.<stage>.json        record
    <sha[:2]>/<sha>.<stage>.fail.json   content-failure marker

A SHA is *done* for a stage when either file exists. There is no index: ``done``
globs, so a lost index can never re-send a page.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from panopticon.fsutil import atomic_write_text
from panopticon.ingest.content import shard_path


class StageStore:
    def __init__(self, root: Path, stage: str) -> None:
        self.root = root
        self._record = f".{stage}.json"
        self._failure = f".{stage}.fail.json"

    def done(self) -> set[str]:
        """SHAs with a record or a fail marker for this stage."""
        return {
            path.name.removesuffix(suffix)
            for suffix in (self._record, self._failure)
            for path in self.root.glob(f"??/*{suffix}")
            if not path.name.startswith(".")
        }

    def put(self, sha: str, record: Mapping[str, Any]) -> None:
        self._write(shard_path(self.root, sha, self._record), record)

    def put_failure(self, sha: str, marker: Mapping[str, Any]) -> None:
        self._write(shard_path(self.root, sha, self._failure), marker)

    @staticmethod
    def _write(path: Path, data: Mapping[str, Any]) -> None:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
