"""AMO (addons.mozilla.org) signing status: "are we there yet?" for a submission.

`just sign-extension` (`web-ext sign`) uploads a version and waits for it to be
signed, but cannot resume once it gives up. This checks a submitted version and,
once AMO has signed it, downloads the .xpi. One-shot: run it again later.

Pure core (token, manifest, status mapping) + a thin shell whose HTTP, env and
clock are injected for tests.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

API = "https://addons.mozilla.org/api/v5/addons/"
TOKEN_TTL_S = 60  # AMO accepts at most 5 minutes.

EXIT_READY = 0
EXIT_FAILED = 1
EXIT_PENDING = 2

# AMO `file.status` -> our state.
_FILE_STATES = {"public": "approved", "unreviewed": "pending", "disabled": "rejected"}


@dataclass(frozen=True)
class Submission:
    addon_id: str
    version: str


@dataclass(frozen=True)
class Status:
    state: Literal["approved", "pending", "rejected"]
    file_url: str | None = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_token(key: str, secret: str, *, now: int, nonce: str) -> str:
    """AMO API auth token: HS256 JWT, issuer = API key, unique `jti` per request."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": key, "jti": nonce, "iat": now, "exp": now + TOKEN_TTL_S}
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, payload)
    )
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def submission_from_manifest(manifest: Mapping) -> Submission:
    gecko_id = manifest["browser_specific_settings"]["gecko"]["id"]
    return Submission(gecko_id, manifest["version"])


def version_url(sub: Submission) -> str:
    # The `v` prefix forces lookup by version number, even for a dotless version.
    return f"{API}addon/{quote(sub.addon_id, safe='')}/versions/v{sub.version}/"


def status_of(version: Mapping) -> Status:
    file = version.get("file")
    if not file:
        return Status("pending")
    state = _FILE_STATES.get(file["status"])
    if state is None:
        raise ValueError(f"unknown AMO file status: {file['status']!r}")
    return Status(state, file["url"] if state == "approved" else None)


def artifact_name(file_url: str) -> str:
    return urlparse(file_url).path.rsplit("/", 1)[-1]


# --- shell --------------------------------------------------------------------

Get = Callable[[str, str], bytes]  # (url, jwt) -> body; raises HTTPError


def http_get(url: str, token: str) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"JWT {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(
    argv: list[str] | None = None,
    *,
    get: Get = http_get,
    env: Mapping[str, str] = os.environ,
    now: Callable[[], float] = time.time,
) -> int:
    parser = argparse.ArgumentParser(
        prog="panopticon-amo",
        description="Check an AMO submission; download the signed .xpi once approved.",
    )
    parser.add_argument("manifest", type=Path, help="extension manifest.json")
    parser.add_argument("version", nargs="?", help="version to check (default: manifest's)")
    parser.add_argument("--out", type=Path, default=Path("web-ext-artifacts"))
    args = parser.parse_args(argv)

    key, secret = env.get("WEB_EXT_API_KEY"), env.get("WEB_EXT_API_SECRET")
    if not (key and secret):
        print("set WEB_EXT_API_KEY and WEB_EXT_API_SECRET", file=sys.stderr)
        return EXIT_FAILED

    def fetch(url: str) -> bytes:
        return get(url, jwt_token(key, secret, now=int(now()), nonce=secrets.token_hex(16)))

    sub = submission_from_manifest(json.loads(args.manifest.read_text()))
    if args.version:
        sub = Submission(sub.addon_id, args.version)

    try:
        return _check(sub, fetch, args.out)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            print(f"no submission of {sub.addon_id} {sub.version} on AMO", file=sys.stderr)
        else:
            print(f"AMO API error {err.code}: {_detail(err)}", file=sys.stderr)
        return EXIT_FAILED


def _check(sub: Submission, fetch: Callable[[str], bytes], out: Path) -> int:
    status = status_of(json.loads(fetch(version_url(sub))))
    if status.state == "pending":
        print(f"{sub.version}: not yet — awaiting signing/review")
        return EXIT_PENDING
    if status.state == "rejected":
        print(f"{sub.version}: rejected or disabled on AMO", file=sys.stderr)
        return EXIT_FAILED

    dest = out / artifact_name(status.file_url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(fetch(status.file_url))
    print(f"{sub.version}: signed → {dest}")
    return EXIT_READY


def _detail(err: urllib.error.HTTPError) -> str:
    """AMO's `{"detail": ...}` error message, else the raw reason."""
    try:
        return json.loads(err.read())["detail"]
    except (ValueError, KeyError, TypeError):
        return str(err.reason)


if __name__ == "__main__":
    sys.exit(main())
