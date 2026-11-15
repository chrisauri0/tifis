"""Gaia DR3 sources around a position, from the bulk files on the ESA CDN.

Those are 3386 gzip CSV files of ~230 MB, ordered by source_id and so by
HEALPix pixel. A file is streamed once, split into order-8 pixel tiles on disk
as it goes, and a request is answered as soon as the pixels it needs have gone
by; the rest of the file keeps filling the cache for neighboring fields.

The tiles and the index use the same layout as the original Go proxy, so an
existing cache directory keeps working.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass

import numpy as np

from .. import net
from ..num import parse_float, parse_int
from .healpix import disc_pixels, pixel_of
from .ranges import RangeReader

DEFAULT_BASE = "https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/"
# The CDN's file browser lists this S3-style bucket.
DEFAULT_LIST = "https://gaia.eu-1.cdn77-storage.com/?prefix=Gaia/gdr3/gaia_source/&delimiter=/"
# Epoch of Gaia DR3 positions, J2016.0.
EPOCH_MJD = 57388.5

# 40 bytes per source, little-endian, no header.
TILE_DTYPE = np.dtype([("source_id", "<i8"), ("ra", "<f8"), ("dec", "<f8"), ("parallax", "<f4"),
                       ("pmra", "<f4"), ("pmdec", "<f4"), ("g", "<f4")])
assert TILE_DTYPE.itemsize == 40

WANTED = ("source_id", "ra", "dec", "parallax", "pmra", "pmdec", "phot_g_mean_mag")
MAX_LINE = 1 << 20

_FILE_RE = re.compile(r"GaiaSource_(\d+)-(\d+)\.csv\.gz$")


class GaiaError(Exception):
    pass


@dataclass
class Star:
    source_id: int
    ra: float
    dec: float
    parallax: float  # mas; NaN when Gaia has no astrometric solution
    pmra: float  # mas/yr, includes cos(dec)
    pmdec: float
    g: float


@dataclass(frozen=True)
class SourceFile:
    name: str
    lo: int  # order-8 pixel range, inclusive
    hi: int
    size: int


class _Stream:
    def __init__(self, f: SourceFile):
        self.cond = threading.Condition()
        self.done = -1  # pixels below this are on disk
        self.finished = False
        self.err: BaseException | None = None
        self.file = f
        self.reader: RangeReader | None = None


class Store:
    def __init__(self, directory: str | os.PathLike, base: str = DEFAULT_BASE, list_url: str = DEFAULT_LIST,
                 parallel: int = 8, chunk: int = 4 << 20):
        self.dir = os.fspath(directory)
        os.makedirs(os.path.join(self.dir, "tiles"), exist_ok=True)
        self.base, self.list_url = base, list_url
        # Parallel range requests per file and their size.
        self.parallel, self.chunk = parallel, chunk
        self._lock = threading.Lock()
        self._files: list[SourceFile] | None = None
        self._streams: dict[str, _Stream] = {}
        # Each stream takes several connections and a CPU decompressing.
        self._slots = threading.Semaphore(2)

    # ---------- queries ----------

    def progress(self, ra: float, dec: float, radius: float) -> list[dict]:
        """The bulk files being streamed right now for a cone."""
        pixels = disc_pixels(ra, dec, radius)
        out = []
        with self._lock:
            streams = list(self._streams.values())
        for st in streams:
            f = st.file
            if not any(f.lo <= p <= f.hi for p in pixels):
                continue
            frac = 0.0
            if st.reader is not None and f.size > 0:
                frac = st.reader.bytes_read / f.size
            out.append({"file": f.name, "fraction": frac, "mb": f.size / 1e6})
        out.sort(key=lambda p: p["file"])
        return out

    def cone(self, ra: float, dec: float, radius: float, timeout: float = 20 * 60) -> list[Star]:
        """Sources whose Gaia position is within radius degrees of (ra, dec).
        Blocks until the tiles it needs are on disk."""
        deadline = time.monotonic() + timeout
        files = self.index(deadline)
        out = []
        for pix in disc_pixels(ra, dec, radius):
            self._ensure(files, pix, deadline)
            for st in self.read_tile(pix):
                if _separation(ra, dec, st.ra, st.dec) <= radius:
                    out.append(st)
        return out

    def _ensure(self, files: list[SourceFile], pix: int, deadline: float) -> None:
        """Wait until pixel pix is on disk, streaming its file if needed."""
        i = bisect.bisect_left([f.hi for f in files], pix)
        if i == len(files) or files[i].lo > pix:
            raise GaiaError(f"gaia: no bulk file covers pixel {pix}")
        f = files[i]
        if self.have_tile(pix) or self.file_done(f.name):
            return
        st = self._stream(f)
        with st.cond:
            while st.done <= pix and not st.finished:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("gaia: timed out waiting for the bulk file")
                st.cond.wait(min(left, 1.0))
            if st.done <= pix and st.err is not None:
                raise st.err

    # ---------- streaming ----------

    def _stream(self, f: SourceFile) -> _Stream:
        with self._lock:
            st = self._streams.get(f.name)
            if st is not None:
                return st
            st = self._streams[f.name] = _Stream(f)

        def run():
            self._slots.acquire()
            try:
                err = None
                try:
                    self._run(f, st)
                except BaseException as e:  # reported to every waiter
                    err = e
            finally:
                self._slots.release()
            with st.cond:
                st.err, st.finished = err, True
                if err is None:
                    st.done = f.hi + 1
                st.cond.notify_all()
            with self._lock:
                self._streams.pop(f.name, None)

        threading.Thread(target=run, daemon=True, name=f"gaia-{f.name}").start()
        return st

    def _run(self, f: SourceFile, st: _Stream) -> None:
        """Stream one bulk file into tiles. It is not tied to any request: once
        started it finishes, so the whole file ends up cached."""
        rr = RangeReader(self.base + f.name, f.size, self.chunk, self.parallel)
        st.reader = rr
        cols: list[int] | None = None
        cur = -1
        tile: list[Star] = []

        def flush(nxt: int) -> None:
            nonlocal cur, tile
            if cur >= 0:
                self.write_tile(cur, tile)
            tile, cur = [], nxt
            with st.cond:
                st.done = nxt
                st.cond.notify_all()

        for line in _gzip_lines(rr, f.name):
            if not line or line[0] == 0x23:  # '#'
                continue
            line = line.rstrip(b"\r\n")
            if cols is None:
                try:
                    cols = columns(line)
                except GaiaError as e:
                    raise GaiaError(f"gaia: {f.name}: {e}") from None
                continue
            star = parse_row(line, cols)
            if star is not None:
                pix = pixel_of(star.source_id)
                if pix != cur:
                    flush(pix)
                tile.append(star)
        flush(f.hi + 1)
        with open(os.path.join(self.dir, "done-" + f.name), "wb"):
            pass

    # ---------- tiles ----------

    def tile_path(self, pix: int) -> str:
        return os.path.join(self.dir, "tiles", str(pix // 1000), f"{pix}.bin")

    def have_tile(self, pix: int) -> bool:
        return os.path.exists(self.tile_path(pix))

    def file_done(self, name: str) -> bool:
        return os.path.exists(os.path.join(self.dir, "done-" + name))

    def write_tile(self, pix: int, stars: list[Star]) -> None:
        a = np.array([(s.source_id, s.ra, s.dec, s.parallax, s.pmra, s.pmdec, s.g) for s in stars],
                     dtype=TILE_DTYPE)
        p = self.tile_path(pix)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(a.tobytes())
        os.replace(tmp, p)

    def read_tile(self, pix: int) -> list[Star]:
        """Sources of a pixel; a missing tile in a finished file means none."""
        try:
            with open(self.tile_path(pix), "rb") as fh:
                buf = fh.read()
        except FileNotFoundError:
            return []
        a = np.frombuffer(buf, dtype=TILE_DTYPE, count=len(buf) // TILE_DTYPE.itemsize)
        return [Star(int(r["source_id"]), float(r["ra"]), float(r["dec"]), float(r["parallax"]),
                     float(r["pmra"]), float(r["pmdec"]), float(r["g"])) for r in a]

    # ---------- index ----------

    def index(self, deadline: float | None = None) -> list[SourceFile]:
        """The bulk files and their pixel ranges, from disk after the first time."""
        if deadline is None:
            deadline = time.monotonic() + 600
        with self._lock:
            if self._files is not None:
                return self._files
        path = os.path.join(self.dir, "index.json")
        try:
            with open(path, "rb") as fh:
                raw = json.load(fh)
            files = [SourceFile(str(d["Name"]), int(d["Lo"]), int(d["Hi"]), int(d["Size"])) for d in raw]
            if files:
                with self._lock:
                    self._files = files
                return files
        except (OSError, ValueError, KeyError, TypeError):
            pass

        files = []
        marker = ""
        while True:
            url = self.list_url
            if marker:
                url += "&marker=" + urllib.parse.quote_plus(marker)
            truncated, contents = self._list(url, deadline)
            for key, size in contents:
                m = _FILE_RE.search(key)
                if m is None:
                    continue
                files.append(SourceFile(os.path.basename(key), int(m.group(1)), int(m.group(2)), size))
            if not truncated or not contents:
                break
            marker = contents[-1][0]
        if not files:
            raise GaiaError("gaia: the bulk file listing is empty")
        files.sort(key=lambda f: f.lo)
        try:
            with open(path, "w") as fh:
                json.dump([{"Name": f.name, "Lo": f.lo, "Hi": f.hi, "Size": f.size} for f in files], fh)
        except OSError:
            pass
        with self._lock:
            self._files = files
        return files

    def _list(self, url: str, deadline: float) -> tuple[bool, list[tuple[str, int]]]:
        try:
            body = net.get(url, deadline)
        except net.StatusError as e:
            raise GaiaError(f"gaia: listing: HTTP {e.code}") from None
        except net.NETWORK_ERRORS as e:
            raise GaiaError(f"gaia: listing: {e}") from e
        root = ET.fromstring(body)

        def local(el) -> str:
            return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""

        truncated = False
        contents = []
        for el in root:
            if local(el) == "IsTruncated":
                truncated = (el.text or "").strip() in ("1", "t", "T", "true", "TRUE", "True")
            elif local(el) == "Contents":
                key, size = "", 0
                for c in el:
                    if local(c) == "Key":
                        key = (c.text or "").strip()
                    elif local(c) == "Size":
                        size = int((c.text or "0").strip())
                contents.append((key, size))
        return truncated, contents


def _gzip_lines(rr: RangeReader, name: str):
    """Lines (with their newline) of a gzip stream read from rr."""
    d = zlib.decompressobj(zlib.MAX_WBITS | 16)
    pending = b""
    started = False
    while True:
        raw = rr.read(1 << 20)
        if not raw:
            break
        while raw:
            try:
                out = d.decompress(raw)
            except zlib.error as e:
                raise GaiaError(f"gaia: {name}: {e}") from None
            started = True
            raw = b""
            if d.eof:
                # Another gzip member may follow.
                raw = d.unused_data
                d = zlib.decompressobj(zlib.MAX_WBITS | 16)
            if out:
                pending += out
                lines = pending.split(b"\n")
                pending = lines.pop()
                if len(pending) > MAX_LINE:
                    raise GaiaError(f"gaia: {name}: line too long")
                for ln in lines:
                    if len(ln) >= MAX_LINE:
                        raise GaiaError(f"gaia: {name}: line too long")
                    yield ln + b"\n"
    if not started:
        raise GaiaError(f"gaia: {name}: empty file")
    if pending:
        yield pending


def columns(header: bytes) -> list[int]:
    """Indexes of the wanted columns in the CSV header."""
    names = header.split(b",")
    cols = []
    for w in WANTED:
        hits = [i for i, n in enumerate(names) if n == w.encode()]
        if not hits:
            raise GaiaError(f"no {w} column")
        cols.append(hits[-1])
    return cols


def parse_row(line: bytes, cols: list[int]) -> Star | None:
    """The wanted fields of a CSV line. Gaia bulk files have no commas inside
    the fields that matter, so a plain split is enough; 'null' reads as NaN."""
    last = max(cols)
    parts = line.split(b",", last + 1)
    if len(parts) < last + 1:
        return None
    try:
        sid = parse_int(parts[cols[0]])
    except ValueError:
        return None

    def f(k: int) -> float:
        try:
            return parse_float(parts[cols[k]])
        except ValueError:
            return math.nan

    def f32(k: int) -> float:
        return float(np.float32(f(k)))

    return Star(sid, f(1), f(2), f32(3), f32(4), f32(5), f32(6))


def _separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    d = math.pi / 180
    a = math.sin((dec2 - dec1) * d / 2)
    b = math.sin((ra2 - ra1) * d / 2)
    h = a * a + math.cos(dec1 * d) * math.cos(dec2 * d) * b * b
    return 2 * math.asin(math.sqrt(min(1.0, h))) / d
