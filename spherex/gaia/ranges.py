"""Read a remote file in order while fetching the chunks ahead of the reader
over several connections: the Gaia CDN gives about 1 MB/s per connection but
scales with parallel range requests. At most `window` chunks are in memory."""

from __future__ import annotations

import threading
import time

from .. import net

_CHUNK_DEADLINE = 300.0  # seconds for one chunk, including retries


class _Result:
    __slots__ = ("done", "data", "err")

    def __init__(self):
        self.done = threading.Event()
        self.data = b""
        self.err: BaseException | None = None


class RangeReader:
    def __init__(self, url: str, size: int, chunk: int, window: int):
        self.url, self.size, self.chunk, self.window = url, size, chunk, window
        self._results: list[_Result | None] = [None] * ((size + chunk - 1) // chunk)
        self._next = 0  # next chunk to start
        self._cur = 0  # chunk being read
        self._buf = memoryview(b"")
        self._read = 0  # bytes handed to the reader, for progress
        self._lock = threading.Lock()
        for _ in range(window):
            self._start()

    @property
    def bytes_read(self) -> int:
        with self._lock:
            return self._read

    def _start(self) -> None:
        if self._next >= len(self._results):
            return
        i = self._next
        self._next += 1
        res = self._results[i] = _Result()
        threading.Thread(target=self._fetch_chunk, args=(i, res), daemon=True, name=f"gaia-range-{i}").start()

    def _fetch_chunk(self, i: int, res: _Result) -> None:
        lo = i * self.chunk
        hi = min(lo + self.chunk, self.size) - 1
        for attempt in range(4):
            if attempt > 0:
                time.sleep(attempt * 2)
            try:
                res.data = self._fetch(lo, hi)
                res.err = None
                break
            except Exception as e:  # retried, then reported to the reader
                res.err = e
        res.done.set()

    def _fetch(self, lo: int, hi: int) -> bytes:
        try:
            data = net.get(self.url, time.monotonic() + _CHUNK_DEADLINE,
                            headers={"Range": f"bytes={lo}-{hi}"}, expect=206)
        except net.StatusError as e:
            raise OSError(f"gaia: range {lo}-{hi}: HTTP {e.code}") from None
        if len(data) != hi - lo + 1:
            raise OSError(f"gaia: range {lo}-{hi}: got {len(data)} bytes")
        return data

    def read(self, n: int = -1) -> bytes:
        """Up to n bytes (n < 0: the rest of the current chunk); b'' at the end."""
        while len(self._buf) == 0:
            if self._cur >= len(self._results):
                return b""
            res = self._results[self._cur]
            res.done.wait()
            if res.err is not None:
                raise res.err
            self._results[self._cur] = None
            self._cur += 1
            self._buf = memoryview(res.data)
            self._start()
        if n < 0 or n > len(self._buf):
            n = len(self._buf)
        out = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        with self._lock:
            self._read += n
        return out
