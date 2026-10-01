"""Tests for the AMO signing-status checker (`just fetch-extension`)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import urllib.error
from pathlib import Path

import pytest

from panopticon.amo import (
    EXIT_FAILED,
    EXIT_PENDING,
    EXIT_READY,
    Status,
    Submission,
    artifact_name,
    jwt_token,
    main,
    status_of,
    submission_from_manifest,
    version_url,
)

ADDON = "panopticon-firefox@panopticon.local"
ENV = {"WEB_EXT_API_KEY": "user:1:2", "WEB_EXT_API_SECRET": "s3cret"}
XPI_URL = "https://addons.mozilla.org/firefox/downloads/file/9/abc-0.2.3.xpi"


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _manifest(tmp_path: Path, version: str = "0.2.3") -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"version": version, "browser_specific_settings": {"gecko": {"id": ADDON}}})
    )
    return path


def _version(file_status: str | None) -> dict:
    file = None if file_status is None else {"status": file_status, "url": XPI_URL}
    return {"version": "0.2.3", "channel": "unlisted", "file": file}


class FakeAmo:
    """Serves canned responses by URL (bytes, or an HTTP status to fail with; unknown
    URLs 404); records the token of each request."""

    def __init__(self, responses: dict[str, bytes | int]) -> None:
        self.responses = responses
        self.tokens: list[str] = []

    def __call__(self, url: str, token: str) -> bytes:
        self.tokens.append(token)
        response = self.responses.get(url, 404)
        if isinstance(response, int):
            body = json.dumps({"detail": f"AMO says {response}"}).encode()
            raise urllib.error.HTTPError(url, response, "Error", {}, io.BytesIO(body))
        return response


def _run(tmp_path: Path, amo: FakeAmo, *args: str, env: dict | None = None) -> int:
    argv = [str(_manifest(tmp_path)), "--out", str(tmp_path / "out"), *args]
    return main(argv, get=amo, env=ENV if env is None else env, now=lambda: 1_700_000_000)


# --- pure ---------------------------------------------------------------------


def test_jwt_token_is_hs256_signed_with_issuer_and_short_expiry() -> None:
    token = jwt_token("user:1:2", "s3cret", now=1000, nonce="n1")
    header, payload, sig = token.split(".")

    assert json.loads(_b64decode(header)) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(_b64decode(payload)) == {
        "iss": "user:1:2",
        "jti": "n1",
        "iat": 1000,
        "exp": 1060,
    }
    expected = hmac.new(b"s3cret", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert _b64decode(sig) == expected


def test_submission_from_manifest_reads_gecko_id_and_version() -> None:
    manifest = {"version": "0.2.3", "browser_specific_settings": {"gecko": {"id": ADDON}}}
    assert submission_from_manifest(manifest) == Submission(ADDON, "0.2.3")


def test_version_url_forces_lookup_by_version_number() -> None:
    # A `v` prefix stops AMO treating a dotless version as a numeric id.
    url = version_url(Submission(ADDON, "3"))
    assert url == (
        "https://addons.mozilla.org/api/v5/addons/addon/"
        "panopticon-firefox%40panopticon.local/versions/v3/"
    )


@pytest.mark.parametrize(
    ("file_status", "expected"),
    [
        ("public", Status("approved", XPI_URL)),
        ("unreviewed", Status("pending")),
        ("disabled", Status("rejected")),
        (None, Status("pending")),
    ],
)
def test_status_of_maps_file_status(file_status: str | None, expected: Status) -> None:
    assert status_of(_version(file_status)) == expected


def test_status_of_rejects_unknown_file_status() -> None:
    with pytest.raises(ValueError, match="mystery"):
        status_of(_version("mystery"))


def test_artifact_name_is_the_url_basename() -> None:
    assert artifact_name(XPI_URL) == "abc-0.2.3.xpi"


# --- shell --------------------------------------------------------------------


def test_main_downloads_approved_xpi(tmp_path: Path, capsys) -> None:
    amo = FakeAmo(
        {
            version_url(Submission(ADDON, "0.2.3")): json.dumps(_version("public")).encode(),
            XPI_URL: b"signed-bytes",
        }
    )

    assert _run(tmp_path, amo) == EXIT_READY
    assert (tmp_path / "out" / "abc-0.2.3.xpi").read_bytes() == b"signed-bytes"
    assert "abc-0.2.3.xpi" in capsys.readouterr().out
    # Each request carries a fresh token: AMO rejects a reused jti.
    assert len(amo.tokens) == 2 and amo.tokens[0] != amo.tokens[1]


def test_main_reports_pending_without_downloading(tmp_path: Path, capsys) -> None:
    amo = FakeAmo(
        {version_url(Submission(ADDON, "0.2.3")): json.dumps(_version("unreviewed")).encode()}
    )

    assert _run(tmp_path, amo) == EXIT_PENDING
    assert not (tmp_path / "out").exists()
    assert "not yet" in capsys.readouterr().out


def test_main_reports_rejected(tmp_path: Path, capsys) -> None:
    amo = FakeAmo(
        {version_url(Submission(ADDON, "0.2.3")): json.dumps(_version("disabled")).encode()}
    )

    assert _run(tmp_path, amo) == EXIT_FAILED
    assert "rejected" in capsys.readouterr().err


def test_main_checks_an_explicit_earlier_version(tmp_path: Path) -> None:
    amo = FakeAmo(
        {
            version_url(Submission(ADDON, "0.2.2")): json.dumps(_version("public")).encode(),
            XPI_URL: b"old",
        }
    )

    assert _run(tmp_path, amo, "0.2.2") == EXIT_READY


def test_main_reports_unknown_version(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, FakeAmo({})) == EXIT_FAILED
    assert "no submission" in capsys.readouterr().err


def test_main_requires_credentials(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, FakeAmo({}), env={}) == EXIT_FAILED
    assert "WEB_EXT_API_KEY" in capsys.readouterr().err


def test_main_reports_api_errors_with_amo_detail(tmp_path: Path, capsys) -> None:
    amo = FakeAmo({version_url(Submission(ADDON, "0.2.3")): 401})

    assert _run(tmp_path, amo) == EXIT_FAILED
    err = capsys.readouterr().err
    assert "401" in err and "AMO says 401" in err
