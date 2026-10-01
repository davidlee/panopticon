"""The sole network egress in the package (DEC-002, I2; design §5.2 Client).

``post_json`` sends one request through a fixed opener: redirects refused (the
``Authorization`` header and body never reach another host), proxy environment
ignored, certificates verified. Failures are classified in a fixed order —
``HTTPError`` is a ``URLError``, so it must be checked first — into a fatal
:class:`ProviderUnavailable`, a per-page :class:`PageRejected`, or a bounded
retry that ends in :class:`TransportFailure`.

Logs carry only the status and the failure kind: never bodies, headers or
error bodies (I5).
"""

from __future__ import annotations

import http.client
import logging
import math
import random
import ssl
import time
import urllib.request
from collections.abc import Callable, Mapping
from email.message import Message
from urllib.error import HTTPError, URLError

log = logging.getLogger("panopticon.digest.client")

ATTEMPTS = 4
TIMEOUT = 60.0
MAX_RETRY_AFTER = 60.0


class ProviderUnavailable(Exception):
    """Fatal for the run: auth, payment, a refused redirect or a bad certificate."""

    def __init__(self, status: int | None) -> None:
        super().__init__(f"provider unavailable (status {status})")
        self.status = status


class PageRejected(Exception):
    """The provider refused this page (a content failure, design D13)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"page rejected (status {status})")
        self.status = status


class TransportFailure(Exception):
    """Retries exhausted on a transient fault."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(
    _NoRedirect(),
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)


class _Retry(Exception):
    def __init__(self, kind: str, retry_after: float | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


def post_json(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    *,
    timeout: float = TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> bytes:
    """POST ``body`` as JSON and return the 2xx reply body."""
    request = urllib.request.Request(
        url, data=body, headers={**headers, "Content-Type": "application/json"}, method="POST"
    )
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return _attempt(request, timeout)
        except _Retry as retry:
            log.warning("provider attempt %d/%d failed: %s", attempt, ATTEMPTS, retry.kind)
            if attempt == ATTEMPTS:
                raise TransportFailure(retry.kind) from None
            delay = retry.retry_after
            sleep(delay if delay is not None else 2 ** (attempt - 1) + jitter())
    raise AssertionError("unreachable")


def _attempt(request: urllib.request.Request, timeout: float) -> bytes:
    """One request; classifies every failure per the design §5.2 table, in order."""
    try:
        with _OPENER.open(request, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        e.close()  # the error body is never read
        status = e.code
        if 300 <= status < 400 or status in (401, 402):
            raise ProviderUnavailable(status) from None
        if status in (408, 429) or status >= 500:
            raise _Retry(f"http {status}", _retry_after(e.headers)) from None
        raise PageRejected(status) from None
    except URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise ProviderUnavailable(None) from None
        raise _Retry(type(e.reason).__name__) from None
    except (TimeoutError, OSError, http.client.HTTPException) as e:
        raise _Retry(type(e).__name__) from None


def _retry_after(headers: Message | None) -> float | None:
    """``Retry-After`` in seconds, capped; ``None`` if absent or an HTTP-date."""
    value = headers.get("Retry-After") if headers is not None else None
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER)
