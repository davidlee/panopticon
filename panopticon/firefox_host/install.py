"""Install the Firefox native-messaging manifest.

Firefox locates the native host by reading a JSON manifest from a
well-known per-user directory; the manifest carries the absolute path
to the host binary plus an allowlist of extension IDs that may invoke
it. This module renders that manifest and writes it (or prints it).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from panopticon.fsutil import atomic_write_text

HOST_NAME = "panopticon_firefox"
EXTENSION_ID = "panopticon-firefox@panopticon.local"
DESCRIPTION = "Panopticon Firefox capture bridge"
NIX_STORE = Path("/nix/store")


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
    """Find the absolute path to the host binary.

    Symlinks are kept, not followed: a Nix profile link
    (``~/.nix-profile/bin/…``) tracks rebuilds, while its store target
    is deleted by garbage collection and would leave the manifest
    dangling. A path that is itself in the store is refused.
    """
    found = explicit or shutil.which("panopticon-firefox-host")
    if found is None:
        raise FileNotFoundError(
            "panopticon-firefox-host not on PATH; pass --binary to set it explicitly"
        )
    path = Path(found).absolute()
    if path.is_relative_to(NIX_STORE):
        raise ValueError(
            f"{path} is in the Nix store and will dangle after garbage "
            "collection; pass --binary with a profile path, e.g. "
            "~/.nix-profile/bin/panopticon-firefox-host"
        )
    return str(path)


def install(manifest: Manifest, manifest_path: Path | None = None) -> Path:
    """Write the manifest. Returns the path written."""
    target = manifest_path or default_manifest_path()
    atomic_write_text(target, manifest.to_json() + "\n")
    return target
