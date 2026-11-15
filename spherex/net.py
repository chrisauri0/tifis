"""Plain HTTP GET with a total deadline, on the standard library."""

from __future__ import annotations

import http.client
import threading
import time
import urllib.error
import urllib.request

USER_AGENT = "spherex-sky-timeline/0.1 (+Space Apps 2026)"
# Longest wait for any single socket operation; the deadline bounds the total.
_SOCKET_TIMEOUT = 120.0


class StatusError(Exception):
    """The server answered with an unexpected HTTP status."""

    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.code = code


class Cancelled(Exception):
    """The caller gave up before the request started."""


# Errors a retry may fix: the network, timeouts and broken responses.
NETWORK_ERRORS = (OSError, http.client.HTTPException, TimeoutError)


def get(url: str, deadline: float, headers: dict[str, str] | None = None, expect: int = 200) -> bytes:
    """GET url and return the body. deadline is a time.monotonic() value.
    Raises StatusError for any status other than `expect`, TimeoutError when
    the deadline passes, and network errors as they come."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("deadline exceeded")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        res = urllib.request.urlopen(req, timeout=min(remaining, _SOCKET_TIMEOUT))
    except urllib.error.HTTPError as e:
        e.close()
        raise StatusError(e.code) from None
    with res:
        if res.status != expect:
            raise StatusError(res.status)
        chunks = []
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("deadline exceeded")
            b = res.read(1 << 16)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)


def acquire(sem: threading.Semaphore, cancelled=None) -> None:
    """Wait for a slot; give up with Cancelled when cancelled() turns true."""
    while not sem.acquire(timeout=0.2):
        if cancelled is not None and cancelled():
            raise Cancelled("request abandoned")
