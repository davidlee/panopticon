"""Install the Firefox native-messaging manifest.

Firefox locates the native host by reading a JSON manifest from a
well-known per-user directory; the manifest carries the absolute path
to the host binary plus an allowlist of extension IDs that may invoke
it. This module renders that manifest and writes it (or prints it).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

HOST_NAME = "panopticon_firefox"
EXTENSION_ID = "panopticon-firefox@panopticon.local"
DESCRIPTION = "Panopticon Firefox capture bridge"


@dataclass(frozen=True, slots=True)
class Manifest:
    name: str
    description: str
    path: str
    type: str
    allowed_extensions: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "description": self.description,
                "path": self.path,
                "type": self.type,
                "allowed_extensions": list(self.allowed_extensions),
            },
            indent=2,
        )


def build_manifest(
    host_binary: str,
    *,
    extension_id: str = EXTENSION_ID,
) -> Manifest:
    return Manifest(
        name=HOST_NAME,
        description=DESCRIPTION,
        path=host_binary,
        type="stdio",
        allowed_extensions=(extension_id,),
    )


def default_manifest_path() -> Path:
    return Path.home() / ".mozilla" / "native-messaging-hosts" / f"{HOST_NAME}.json"


def resolve_host_binary(explicit: str | None = None) -> str:
    """Find the absolute path to the host binary."""
    if explicit:
        return str(Path(explicit).resolve())
    found = shutil.which("panopticon-firefox-host")
    if found is None:
        raise FileNotFoundError(
            "panopticon-firefox-host not on PATH; pass --binary to set it explicitly"
        )
    return str(Path(found).resolve())


def install(
    *,
    binary: str | None = None,
    extension_id: str = EXTENSION_ID,
    manifest_path: Path | None = None,
) -> Path:
    """Write the manifest. Returns the path written."""
    host_binary = resolve_host_binary(binary)
    manifest = build_manifest(host_binary, extension_id=extension_id)
    target = manifest_path or default_manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(manifest.to_json() + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target
