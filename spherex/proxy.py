"""The data side of the server: SPHEREx image lists and cutouts from IRSA, and
Gaia DR3 + CatWISE2020 catalogs, all cached on disk.

IRSA queries take from seconds to minutes, so answers are cached and the
challenge's test objects are fetched in the background at startup. The cache
keys and file layout are the same as the original Go proxy's, so an existing
cache directory (~/.cache/spherex-proxy) keeps working.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import threading
import time

from . import net
from .gaia import EPOCH_MJD as GAIA_EPOCH_MJD
from .gaia import Store
from .irsa import Cache, Client, merge, valid_path
from .num import go_round
from .sky import TARGETS, CatalogEntry, time_to_mjd

log = logging.getLogger("spherex")

# The archive receives new images weekly, so a day-old list is fresh enough.
VISITS_TTL = 24 * 3600.0
# Covers the corners of the largest field the app offers (12').
CATALOG_RADIUS = 0.15
# Once Gaia is ready, CatWISE gets this long before the answer goes without it.
CATWISE_GRACE = 20.0


class BadRequest(ValueError):
    """Invalid parameters (HTTP 400)."""


class UpstreamError(Exception):
    """An external service failed (HTTP 502); usually temporary."""


def dumps(v) -> bytes:
    return json.dumps(v, allow_nan=False, separators=(",", ":")).encode()


def round_position(ra: float, dec: float) -> tuple[float, float]:
    """Round to ~2" so nearby requests, and the warm-up, share the cache."""
    return go_round(ra * 2000) / 2000, go_round(dec * 2000) / 2000


def check_position(ra: float, dec: float) -> None:
    if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
        raise BadRequest("ra must be in [0, 360) and dec in [-90, 90] degrees")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Proxy:
    def __init__(self, client: Client, cache: Cache, gaia: Store):
        self.client, self.cache, self.gaia = client, cache, gaia

    def visits_data(self, ra: float, dec: float) -> tuple[bytes, bool]:
        """JSON list of the spectral images covering a position, and whether it
        came from the cache."""
        check_position(ra, dec)
        ra, dec = round_position(ra, dec)

        def fetch() -> bytes:
            # SIA answers in seconds; TAP is slower but sees data ingested in
            # the last day, and is a second way in when SIA is down.
            source = "SIA"
            try:
                v = self.client.visits_sia(ra, dec)
            except Exception as e:
                log.info("SIA failed, trying TAP: %s", e)
                source = "TAP"
                v = self.client.visits_tap(ra, dec)
            return dumps({"ra": ra, "dec": dec, "source": source, "fetched": _utc_now(),
                          "visits": [x.to_json() for x in v]})

        try:
            return self.cache.get(f"visits {ra:.4f} {dec:.4f}", VISITS_TTL, fetch)
        except Exception as e:
            raise UpstreamError(str(e)) from e

    def catalog_data(self, ra: float, dec: float) -> tuple[bytes, bool]:
        """Gaia DR3 (from the ESA CDN) merged with CatWISE2020 (from IRSA).
        Catalogs do not change, so complete answers are cached for good; when
        CatWISE fails the Gaia part is still returned, marked as partial."""
        check_position(ra, dec)
        ra, dec = round_position(ra, dec)
        key = f"catalog {ra:.4f} {dec:.4f} {CATALOG_RADIUS:.3f} gaia-cdn"
        data = self.cache.lookup(key, 0)
        if data is not None:
            return data, True

        # CatWISE has its own cache and keeps going in the background: once
        # Gaia is ready it gets a short grace period, and if IRSA is slow the
        # answer goes out without it and a later request picks it up. When a
        # CatWISE query for this field is already running (an earlier request
        # gave up waiting for it), there is no point waiting again.
        cw_key = f"catwise {ra:.4f} {dec:.4f} {CATALOG_RADIUS:.3f}"
        grace = 1.0 if self.cache.pending(cw_key) else CATWISE_GRACE
        cw_result: dict = {}
        cw_done = threading.Event()

        def catwise():
            try:
                raw, _ = self.cache.get(
                    cw_key, 0,
                    lambda: dumps([e.to_json() for e in self.client.catwise(ra, dec, CATALOG_RADIUS)]))
                cw_result["entries"] = [CatalogEntry.from_json(d) for d in json.loads(raw)]
            except Exception as e:
                cw_result["err"] = e
            finally:
                cw_done.set()

        threading.Thread(target=catwise, daemon=True, name="catwise").start()
        try:
            stars = self.gaia.cone(ra, dec, CATALOG_RADIUS, timeout=20 * 60)
        except Exception as e:
            raise UpstreamError(str(e)) from e
        if cw_done.wait(grace):
            cw, cw_err = cw_result.get("entries", []), cw_result.get("err")
        else:
            cw, cw_err = [], "still waiting for IRSA"

        entries = []
        for st in stars:
            if not st.g < 19:
                continue
            pmra, pmdec = st.pmra, st.pmdec
            if math.isnan(pmra) or math.isnan(pmdec):
                pmra, pmdec = 0.0, 0.0
            entries.append(CatalogEntry("Gaia DR3", f"Gaia DR3 {st.source_id}", st.ra, st.dec, pmra, pmdec,
                                        GAIA_EPOCH_MJD, st.g))
        res = {"ra": ra, "dec": dec, "radius": CATALOG_RADIUS,
               "sources": [e.to_json() for e in merge(entries, cw)]}
        if cw_err is not None:
            log.info("catalog %.4f %.4f without CatWISE: %s", ra, dec, cw_err)
            res["missing"] = ["CatWISE2020"]
        try:
            data = dumps(res)
        except ValueError as e:
            raise UpstreamError(f"catalog: {e}") from e
        if cw_err is None:
            self.cache.put(key, data)
        return data, False

    def cutout_data(self, path: str, ra: float, dec: float, size: float, cancelled=None) -> tuple[bytes, bool]:
        """A cutout without the PSF cube. If cancelled() turns true while the
        request waits for a slot, it gives up; once the download has started it
        finishes and lands in the cache."""
        check_position(ra, dec)
        if not valid_path(path):
            raise BadRequest("path must be a SPHEREx archive file")
        if not (math.isfinite(size) and 0 < size <= 0.3):
            raise BadRequest("size must be in (0, 0.3] degrees")
        key = f"cutout {path} {ra:.6f} {dec:.6f} {size:.5f}"
        try:
            return self.cache.get(key, 0, lambda: self.client.cutout(path, ra, dec, size, cancelled))
        except net.Cancelled:
            raise
        except Exception as e:
            raise UpstreamError(str(e)) from e

    def gaia_progress(self, ra: float, dec: float) -> list[dict]:
        check_position(ra, dec)
        return self.gaia.progress(ra, dec, CATALOG_RADIUS)

    def warm(self) -> None:
        """Fetch the test objects ahead of time, at the positions the app asks
        for, so the first visitor does not wait minutes for IRSA. One query at
        a time, to leave the archive (and the app's own requests) room."""
        now = time_to_mjd()
        for name, fetch in (("visits", self.visits_data), ("catalog", self.catalog_data)):
            for t in TARGETS:
                ra, dec = t.source.position(now)
                start = time.monotonic()
                try:
                    _, hit = fetch(ra, dec)
                except Exception as e:
                    log.info("warm-up %s %s: %s", t.id, name, e)
                    continue
                if not hit:
                    log.info("warm-up %s %s: fetched in %ds", t.id, name, round(time.monotonic() - start))
