"""SL-006 VT-1: the egress client against a local ``http.server`` (design §5.2 Client).

Each row of the ordered failure-classification table, redirect refusal, the
Retry-After cap and proxy bypass. Nothing here leaves 127.0.0.1.
"""

from __future__ import annotations

import socket
import ssl
import struct
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from panopticon.digest.client import (
    ATTEMPTS,
    MAX_RETRY_AFTER,
    PageRejected,
    ProviderUnavailable,
    TransportFailure,
    post_json,
)

CERT = Path(__file__).parent / "fixtures" / "selfsigned-localhost.pem"

type Action = Callable[[BaseHTTPRequestHandler], None]


# --- scripted server --------------------------------------------------------


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Server:
    url: str
    actions: list[Action]
    received: list[Received] = field(default_factory=list)


class _Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # noqa: ANN001 — scripted faults are expected
        pass


@contextmanager
def serve(*actions: Action, tls: bool = False) -> Iterator[Server]:
    """A local server answering each request with the next scripted action."""
    state = Server("", list(actions))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server API
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state.received.append(Received(self.path, dict(self.headers), body))
            state.actions.pop(0)(self)

        def log_message(self, *args: object) -> None:
            pass

    httpd = _Quiet(("127.0.0.1", 0), Handler)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    state.url = f"{'https' if tls else 'http'}://127.0.0.1:{httpd.server_address[1]}/v1"
    thread = threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def reply(status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> Action:
    def act(h: BaseHTTPRequestHandler) -> None:
        h.send_response(status)
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    return act


def ok(body: bytes = b'{"ok":true}') -> Action:
    return reply(200, body)


def reset_mid_body(h: BaseHTTPRequestHandler) -> None:
    """Send headers and part of the body, then RST: ``read()`` sees a raw reset."""
    h.send_response(200)
    h.send_header("Content-Length", "1000")
    h.end_headers()
    h.wfile.write(b"x" * 10)
    h.wfile.flush()
    time.sleep(0.2)
    h.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    h.connection.close()


def garbage_status(h: BaseHTTPRequestHandler) -> None:
    h.wfile.write(b"NOT HTTP\r\n\r\n")
    h.close_connection = True


def stall(seconds: float) -> Action:
    def act(h: BaseHTTPRequestHandler) -> None:
        time.sleep(seconds)
        h.close_connection = True

    return act


# --- helpers ------------------------------------------------------------------


@dataclass
class Sleeps:
    calls: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def post(url: str, sleeps: Sleeps | None = None, **kw: object) -> bytes:
    return post_json(
        url,
        {"Authorization": "Bearer k"},
        b'{"q":1}',
        sleep=sleeps if sleeps is not None else Sleeps(),
        jitter=lambda: 0.0,
        **kw,  # type: ignore[arg-type]
    )


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- success ------------------------------------------------------------------


def test_post_json_sends_body_and_headers_and_returns_the_reply():
    with serve(ok(b'{"choices":[]}')) as srv:
        assert post(srv.url) == b'{"choices":[]}'
    [got] = srv.received
    assert got.body == b'{"q":1}'
    assert got.headers["Authorization"] == "Bearer k"
    assert got.headers["Content-Type"] == "application/json"


# --- fatal: ProviderUnavailable ---------------------------------------------------


@pytest.mark.parametrize("status", [401, 402])
def test_auth_and_payment_statuses_are_fatal_without_retry(status: int):
    """HTTPError is a URLError: classifying it first is what keeps 401 from retrying."""
    sleeps = Sleeps()
    with serve(reply(status, b"secret error body")) as srv:
        with pytest.raises(ProviderUnavailable) as exc:
            post(srv.url, sleeps)
    assert exc.value.status == status
    assert len(srv.received) == 1 and sleeps.calls == []
    assert "secret error body" not in str(exc.value)


def test_redirect_is_fatal_and_never_contacts_the_target():
    with serve() as target, serve(reply(302, headers={"Location": target.url})) as srv:
        with pytest.raises(ProviderUnavailable) as exc:
            post(srv.url)
    assert exc.value.status == 302
    assert target.received == []


def test_certificate_failure_is_fatal_without_retry():
    sleeps = Sleeps()
    with serve(ok(), tls=True) as srv:
        with pytest.raises(ProviderUnavailable) as exc:
            post(srv.url, sleeps)
    assert exc.value.status is None
    assert srv.received == [] and sleeps.calls == []


# --- per page: PageRejected --------------------------------------------------------


@pytest.mark.parametrize("status", [400, 403, 404, 413, 422, 418])
def test_page_specific_4xx_rejects_the_page_without_retry(status: int):
    sleeps = Sleeps()
    with serve(reply(status, b"moderation says no")) as srv:
        with pytest.raises(PageRejected) as exc:
            post(srv.url, sleeps)
    assert exc.value.status == status
    assert len(srv.received) == 1 and sleeps.calls == []


# --- retried ------------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(status: int):
    with serve(reply(status), ok()) as srv:
        assert post(srv.url) == b'{"ok":true}'
    assert len(srv.received) == 2


@pytest.mark.parametrize(
    "fault",
    [reset_mid_body, garbage_status],
    ids=["connection-reset", "http-exception"],
)
def test_socket_and_protocol_faults_are_retried(fault: Action):
    with serve(fault, ok()) as srv:
        assert post(srv.url) == b'{"ok":true}'
    assert len(srv.received) == 2


def test_timeout_is_retried():
    with serve(stall(0.5), ok()) as srv:
        assert post(srv.url, timeout=0.1) == b'{"ok":true}'
    assert len(srv.received) == 2


def test_connection_refused_exhausts_retries_into_transport_failure():
    sleeps = Sleeps()
    with pytest.raises(TransportFailure):
        post(f"http://127.0.0.1:{closed_port()}/v1", sleeps)
    assert len(sleeps.calls) == ATTEMPTS - 1


def test_exhausted_retries_raise_transport_failure_after_the_attempt_budget():
    sleeps = Sleeps()
    with serve(*[reply(503)] * ATTEMPTS) as srv:
        with pytest.raises(TransportFailure):
            post(srv.url, sleeps)
    assert len(srv.received) == ATTEMPTS
    assert sleeps.calls == sorted(sleeps.calls) and len(sleeps.calls) == ATTEMPTS - 1


def test_retry_after_is_honoured():
    sleeps = Sleeps()
    with serve(reply(429, headers={"Retry-After": "7"}), ok()) as srv:
        post(srv.url, sleeps)
    assert sleeps.calls == [7.0]


def test_large_retry_after_is_capped():
    sleeps = Sleeps()
    with serve(reply(429, headers={"Retry-After": "3600"}), ok()) as srv:
        post(srv.url, sleeps)
    assert sleeps.calls == [MAX_RETRY_AFTER]


# --- proxy bypass ---------------------------------------------------------------


def test_proxy_environment_is_ignored(monkeypatch: pytest.MonkeyPatch):
    """Plain-http fixture, so HTTP_PROXY (not HTTPS_PROXY) makes this non-vacuous."""
    bogus = f"http://127.0.0.1:{closed_port()}"
    for var in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(var, bogus)
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    assert urllib.request.getproxies()["http"] == bogus  # stdlib would use it
    with serve(ok()) as srv:
        assert post(srv.url) == b'{"ok":true}'
    assert len(srv.received) == 1
