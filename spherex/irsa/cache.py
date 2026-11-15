"""Disk cache that merges concurrent requests for the same key, so a slow TAP
query runs once even if several tabs ask for it."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from typing import Callable


class _Call:
    __slots__ = ("done", "data", "err")

    def __init__(self):
        self.done = threading.Event()
        self.data: bytes | None = None
        self.err: BaseException | None = None


class Cache:
    def __init__(self, directory: str | os.PathLike):
        self.dir = os.fspath(directory)
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._inflight: dict[str, _Call] = {}

    def path(self, key: str) -> str:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(self.dir, h[:2], h)

    def lookup(self, key: str, ttl: float) -> bytes | None:
        """A cached value younger than ttl seconds (0 means forever)."""
        p = self.path(key)
        try:
            st = os.stat(p)
            if ttl == 0 or time.time() - st.st_mtime < ttl:
                with open(p, "rb") as fh:
                    return fh.read()
        except OSError:
            pass
        return None

    def get(self, key: str, ttl: float, fetch: Callable[[], bytes]) -> tuple[bytes, bool]:
        """The cached value if younger than ttl, otherwise fetch() stored.
        Returns (data, hit). Errors from fetch are raised and not cached."""
        data = self.lookup(key, ttl)
        if data is not None:
            return data, True
        with self._lock:
            call = self._inflight.get(key)
            leader = call is None
            if leader:
                call = self._inflight[key] = _Call()
        if not leader:
            call.done.wait()
            if call.err is not None:
                raise call.err
            return call.data, False
        try:
            call.data = fetch()
            self._store(self.path(key), call.data)
        except BaseException as e:
            call.err = e
            raise
        finally:
            with self._lock:
                del self._inflight[key]
            call.done.set()
        return call.data, False

    def pending(self, key: str) -> bool:
        """Whether a fetch for key is running right now."""
        with self._lock:
            return key in self._inflight

    def put(self, key: str, data: bytes) -> None:
        """Store a value, for answers that are only worth caching when complete."""
        self._store(self.path(key), data)

    @staticmethod
    def _store(p: str, data: bytes) -> None:
        """Write atomically so a crash never leaves half a file in the cache."""
        d = os.path.dirname(p)
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
        except OSError:
            return
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, p)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
