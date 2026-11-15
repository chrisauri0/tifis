"""Local stand-ins for IRSA and the Gaia CDN, so the real-data path can be
tested end to end without network: SIA lists images of Barnard's Star in
several detectors and dates, every cutout is the real DR1 fixture, CatWISE
answers a small table and the Gaia CDN serves one bulk file."""

from __future__ import annotations

import gzip
import math
from pathlib import Path

from spherex import gaia, sky

from .conftest import FakeServer, serve_range

DATA = Path(__file__).parent / "data"
NOW = 61356


def barnard_position(mjd=NOW):
    return sky.TARGETS[0].source.position(mjd)


def sia_votable() -> bytes:
    rows = []
    # Exposures over three seasons; each covers a pair of detectors.
    pairs = [(1, 4), (2, 5), (3, 6)]
    k = 0
    for season_start in (60800.0, 60990.0, 61170.0):
        for j in range(6):
            mjd = season_start + 2.5 * j
            k += 1
            exp = f"2025W{20 + j:02d}_2C_{k:04d}_1"
            for det in pairs[j % 3]:
                url = (f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/x/l2b-v27/{det}/"
                       f"level2_{exp}D{det}_spx_l2b-v27.fits")
                rows.append(f"<TR><TD>{url}</TD><TD>{mjd + 0.001 * det}</TD></TR>")
    return ("<VOTABLE><RESOURCE><TABLE><FIELD name='access_url'/><FIELD name='t_min'/><DATA><TABLEDATA>"
            + "".join(rows) + "</TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>").encode()


def gaia_bulk(ra0: float, dec0: float) -> tuple[bytes, str]:
    gra, gdec = sky.TARGETS[0].source.position(gaia.EPOCH_MJD)
    stars = [(gra, gdec, -801.551, 10362.394, 8.19)]
    for i in range(40):
        a = 2 * math.pi * i / 40
        r = 0.02 + 0.1 * ((i * 7) % 10) / 10
        stars.append((ra0 + r * math.cos(a) / math.cos(math.radians(dec0)), dec0 + r * math.sin(a), 2.0, -3.0,
                      12 + (i % 8)))
    pixels = gaia.disc_pixels(ra0, dec0, 0.2)
    rows = []
    for i, (ra, dec, pmra, pmdec, g) in enumerate(stars):
        sid = (gaia.ang2pix(12, ra, dec) << 35) + i
        rows.append((sid, ra, dec, pmra, pmdec, g))
    rows.sort()
    lo = min(min(pixels), gaia.pixel_of(rows[0][0]))
    hi = max(max(pixels), gaia.pixel_of(rows[-1][0]))
    lines = ["# %ECSV 1.0", "solution_id,source_id,ra,dec,parallax,pmra,pmdec,phot_g_mean_mag"]
    lines += [f"1,{sid},{ra!r},{dec!r},1.0,{pmra!r},{pmdec!r},{g!r}" for sid, ra, dec, pmra, pmdec, g in rows]
    return gzip.compress(("\n".join(lines) + "\n").encode()), f"GaiaSource_{lo:06d}-{hi:06d}.csv.gz"


class FakeArchive:
    def __init__(self, cutout_failures: int = 0):
        self.cutout = (DATA / "barnard_d6.fits").read_bytes()
        self.failures_left = cutout_failures
        ra, dec = barnard_position()
        self.bulk, self.bulk_name = gaia_bulk(ra, dec)
        self.server = FakeServer(self.handle)
        self.url = self.server.url

    def handle(self, path, q, headers):
        if path == "/SIA":
            return 200, sia_votable(), {}
        if path == "/TAP/sync":
            if "catwise_2020" in q["QUERY"][0]:
                ra, dec = barnard_position(57170)
                return 200, (f"source_name,ra,dec,pmra,pmdec,w2mpro\nJ175747.66+044419.7,{ra},{dec},-0.80,10.36,4.1\n"
                             ).encode(), {}
            return 400, b"unexpected", {}
        if path.startswith("/ibe/data/spherex/"):
            if self.failures_left > 0:
                self.failures_left -= 1
                return 503, b"busy", {}
            return 200, self.cutout, {}
        if path == "/gaia/list":
            return 200, (f"<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>Gaia/gdr3/gaia_source/"
                         f"{self.bulk_name}</Key><Size>{len(self.bulk)}</Size></Contents></ListBucketResult>").encode(), {}
        if path == "/gaia/files/" + self.bulk_name:
            return serve_range(self.bulk, headers)
        return 404, b"not found", {}

    def close(self):
        self.server.close()
