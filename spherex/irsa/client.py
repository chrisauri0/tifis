"""The SPHEREx archive at IRSA: which spectral images cover a position (SIA or
TAP), small cutouts of them without the PSF cube, and CatWISE2020."""

from __future__ import annotations

import csv
import io
import math
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from .. import fits, net
from ..num import parse_float
from ..sky import CatalogEntry, Source, separation

DEFAULT_BASE = "https://irsa.ipac.caltech.edu"

# CatWISE2020 fits positions at this epoch (2015.4) together with proper motions.
CATWISE_EPOCH_MJD = 57170.0

# Time limits for one request to IRSA once it has a slot; TAP queries on big
# catalogs take minutes.
CUTOUT_LIMIT = 90.0
QUERY_LIMIT = 8 * 60.0

_FILE_RE = re.compile(r"level2_(\w+?_\d+_\d+)D(\d)_spx", re.ASCII)
_PREFIX = "ibe/data/spherex/"


class IrsaError(Exception):
    pass


@dataclass
class Visit:
    """One spectral image (one detector, one exposure) covering a position."""

    path: str  # relative to the archive root, e.g. ibe/data/spherex/...
    mjd: float
    detector: int  # 1-6
    exposure: str  # shared by the detectors of the same exposure
    release: str  # dr1, qr3, ...

    def to_json(self) -> dict:
        return asdict(self)


class Client:
    """Limits concurrent requests to IRSA; the archive tutorials suggest around
    ten parallel cutout requests at most. Each kind of request has its own
    slots: slow catalog queries must not hold up the visit lists the app is
    waiting for, nor the cutouts."""

    def __init__(self, base: str = DEFAULT_BASE, parallel: int = 8):
        self.base = base.rstrip("/")
        self.cutouts = threading.Semaphore(parallel)
        self.visits_slots = threading.Semaphore(2)
        self.catalogs = threading.Semaphore(2)

    def visits_tap(self, ra: float, dec: float) -> list[Visit]:
        """Spectral images whose footprint contains the position, oldest first.
        TAP sees new data as soon as it is ingested, unlike SIA, at the cost of
        slower queries (tens of seconds)."""
        query = (
            "SELECT a.uri, p.time_bounds_lower, p.energy_bandpassname\n"
            "FROM spherex.artifact a\n"
            "JOIN spherex.plane p ON a.planeid = p.planeid\n"
            f"WHERE 1 = CONTAINS(POINT('ICRS', {ra:.6f}, {dec:.6f}), p.poly)\n"
            "ORDER BY p.time_bounds_lower"
        )
        q = urllib.parse.urlencode(sorted({"LANG": "ADQL", "FORMAT": "csv", "QUERY": query}.items()))
        try:
            body = self.get(self.visits_slots, f"{self.base}/TAP/sync?{q}", QUERY_LIMIT)
        except net.Cancelled:
            raise
        except Exception as e:
            raise IrsaError(f"irsa: TAP query: {e}") from e
        return parse_visits(body)

    def visits_sia(self, ra: float, dec: float) -> list[Visit]:
        """The same list through Simple Image Access, which answers in seconds
        but lags new data by about a day."""
        q = urllib.parse.urlencode([
            ("COLLECTION", "spherex_dr1"), ("COLLECTION", "spherex_qr3"),
            ("POS", f"circle {ra:.6f} {dec:.6f} 0.0003"), ("RESPONSEFORMAT", "VOTABLE"),
        ])
        try:
            body = self.get(self.visits_slots, f"{self.base}/SIA?{q}", QUERY_LIMIT)
        except net.Cancelled:
            raise
        except Exception as e:
            raise IrsaError(f"irsa: SIA query: {e}") from e
        try:
            rows = votable_columns(body, "access_url", "t_min")
        except Exception as e:
            raise IrsaError(f"irsa: SIA response: {e}") from e
        return visits_from_rows(rows)

    def cutout(self, path: str, ra: float, dec: float, size: float, cancelled=None) -> bytes:
        """Cutout of `size` degrees around (ra, dec) without the EPSF extension,
        a PSF cube that makes up about 95 % of every cutout."""
        if not valid_path(path):
            raise IrsaError("irsa: not a SPHEREx archive path")
        url = f"{self.base}/{path}?center={ra:.6f},{dec:.6f}d&size={size:.5f}"
        try:
            body = self.get(self.cutouts, url, CUTOUT_LIMIT, cancelled)
            hdus = fits.parse(body)
        except net.Cancelled:
            raise
        except Exception as e:
            raise IrsaError(f"irsa: cutout: {e}") from e
        return fits.join([h for h in hdus if h.name() != "EPSF"])

    def catwise(self, ra: float, dec: float, radius: float) -> list[CatalogEntry]:
        """CatWISE2020 sources within radius degrees. CatWISE adds what Gaia
        cannot see, like cold brown dwarfs, with infrared proper motions."""
        query = (
            "SELECT source_name, ra, dec, pmra, pmdec, w2mpro FROM catwise_2020 "
            f"WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) "
            "AND (w1mpro < 15.5 OR w2mpro < 16.5)"
        )
        try:
            rows = self.tap(query)
        except Exception as e:
            raise IrsaError(f"irsa: CatWISE: {e}") from e
        out = []
        for r in rows:
            r = r + [""] * (6 - len(r))
            out.append(CatalogEntry(
                catalog="CatWISE2020", name="CatWISE " + r[0], ra=num(r[1]), dec=num(r[2]),
                pmra=1000 * num(r[3]), pmdec=1000 * num(r[4]), mjd=CATWISE_EPOCH_MJD, mag=num(r[5]),
            ))
        return out

    def tap(self, query: str) -> list[list[str]]:
        """Run an ADQL query and return the CSV rows without the header."""
        q = urllib.parse.urlencode(sorted({"LANG": "ADQL", "FORMAT": "csv", "QUERY": query}.items()))
        body = self.get(self.catalogs, f"{self.base}/TAP/sync?{q}", QUERY_LIMIT)
        try:
            rows = read_csv(body)
        except ValueError:
            rows = []
        if not rows:
            raise IrsaError(f"unexpected TAP response: {body[:200].decode('utf-8', 'replace')}")
        return rows[1:]

    def get(self, slots: threading.Semaphore, url: str, limit: float, cancelled=None) -> bytes:
        """GET with retries of transient failures (network errors and 5xx),
        which the archive returns now and then under load.

        Waiting for a slot ends when cancelled() turns true, so abandoned
        requests leave the queue; once a request to IRSA starts it runs to the
        end (within limit), so its answer still reaches the cache."""
        net.acquire(slots, cancelled)
        try:
            deadline = time.monotonic() + limit
            err: Exception | None = None
            for attempt in range(3):
                if attempt > 0:
                    wait = float(attempt)
                    if time.monotonic() + wait > deadline:
                        raise TimeoutError("deadline exceeded")
                    time.sleep(wait)
                try:
                    return net.get(url, deadline)
                except net.StatusError as e:
                    if e.code < 500:
                        raise
                    err = e
                except net.NETWORK_ERRORS as e:
                    err = e
                if time.monotonic() >= deadline:
                    break
            assert err is not None
            raise err
        finally:
            slots.release()


def read_csv(body: bytes) -> list[list[str]]:
    """CSV rows; every record must have as many fields as the first."""
    rows = list(csv.reader(io.StringIO(body.decode("utf-8"), newline="")))
    if rows and any(len(r) != len(rows[0]) for r in rows):
        raise ValueError("wrong number of fields")
    return rows


def parse_visits(body: bytes) -> list[Visit]:
    try:
        rows = read_csv(body)
    except (ValueError, UnicodeDecodeError, csv.Error) as e:
        raise IrsaError(f"irsa: TAP response: {e}") from e
    if not rows or len(rows[0]) < 2 or rows[0][0] != "uri":
        raise IrsaError(f"irsa: unexpected TAP response: {body[:200].decode('utf-8', 'replace')}")
    return visits_from_rows(rows[1:])


def visits_from_rows(rows: list[list[str]]) -> list[Visit]:
    """(archive path or URL, MJD) pairs to visits. Reprocessed files can appear
    next to older versions of the same exposure; keep one per exposure and
    detector, preferring data releases over quick releases."""
    best: dict[str, Visit] = {}
    for row in rows:
        if len(row) < 2:
            continue
        m = _FILE_RE.search(row[0])
        try:
            mjd = parse_float(row[1])
        except ValueError:
            continue
        if m is None:
            continue
        path = row[0][1:] if row[0].startswith("/") else row[0]
        i = path.find(_PREFIX)
        if i > 0:
            path = path[i:]
        rest = path[len(_PREFIX):] if path.startswith(_PREFIX) else path
        parts = rest.split("/")
        release = parts[0] if len(parts) > 1 else ""
        v = Visit(path=path, mjd=mjd, detector=int(m.group(2)), exposure=m.group(1), release=release)
        key = v.exposure + "/" + m.group(2)
        old = best.get(key)
        if old is None or _rank(v) > _rank(old):
            best[key] = v
    return sorted(best.values(), key=lambda v: (v.mjd, v.detector))


def _rank(v: Visit) -> str:
    return ("1" if v.release.startswith("dr") else "0") + v.path


def valid_path(p: str) -> bool:
    """Only SPHEREx archive files, so the proxy cannot fetch anything else."""
    return (p.startswith(_PREFIX) and p.endswith(".fits") and ".." not in p
            and not any(c in p for c in "?#\\"))


def votable_columns(body: bytes, *names: str) -> list[list[str]]:
    """The named columns of the last table in a TABLEDATA VOTable."""
    root = ET.fromstring(body)

    def local(el) -> str:
        return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""

    def children(el, name):
        return [c for c in el if local(c) == name]

    tables = [t for res in children(root, "RESOURCE") for t in children(res, "TABLE")]
    if not tables:
        raise IrsaError(f"no table in {body[:200].decode('utf-8', 'replace')}")
    t = tables[-1]
    fields = [f.get("name") for f in children(t, "FIELD")]
    idx = []
    for name in names:
        hits = [i for i, f in enumerate(fields) if f == name]
        if not hits:
            raise IrsaError(f"no column {name}")
        idx.append(hits[-1])
    out = []
    for data in children(t, "DATA"):
        for td in children(data, "TABLEDATA"):
            for tr in children(td, "TR"):
                cells = ["".join(c.itertext()) for c in children(tr, "TD")]
                out.append([cells[i] if i < len(cells) else "" for i in idx])
    return out


def merge(gaia: list[CatalogEntry], catwise: list[CatalogEntry]) -> list[CatalogEntry]:
    """Gaia sources plus the CatWISE ones Gaia does not have. CatWISE lists some
    fast movers more than once; the brightest entry is kept."""
    out = list(gaia)
    for e in sorted(catwise, key=lambda e: e.mag):
        if not _duplicate(e, out, len(gaia)):
            out.append(e)
    return out


def _duplicate(e: CatalogEntry, entries: list[CatalogEntry], n_gaia: int) -> bool:
    """Whether e is within 3" of a listed source once both are at e's epoch."""
    for i, o in enumerate(entries):
        s = Source(ra=o.ra, dec=o.dec, pmra=o.pmra, pmdec=o.pmdec, ref_mjd=o.mjd)
        ra, dec = s.position(e.mjd)
        # Split CatWISE detections of one fast mover can sit further apart.
        limit = 3.0 if i < n_gaia else 6.0
        if separation(ra, dec, e.ra, e.dec) * 3600 < limit:
            return True
    return False


def num(s: str) -> float:
    try:
        v = parse_float(s.strip())
    except ValueError:
        return 0.0
    return 0.0 if math.isnan(v) else v
