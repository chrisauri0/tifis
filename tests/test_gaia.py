"""Ports of internal/gaia tests."""

import csv
import gzip
import math
import os
import time
from pathlib import Path

import numpy as np
import pytest

from spherex import gaia
from spherex.gaia.store import _separation

from .conftest import serve_range

DATA = Path(__file__).parent / "data"


def test_ang2pix_matches_gaia_source_ids():
    # The pixel in a source_id comes from the position Gaia had for the source
    # when it was numbered, not exactly the DR3 one, so a few sources near
    # pixel edges (and fast movers like Barnard's Star) fall in a neighbor.
    # A wrong algorithm would miss nearly all of them.
    with open(DATA / "healpix_rows.csv") as fh:
        rows = list(csv.reader(fh))[1:]
    miss12 = miss8 = 0
    for sid, ra, dec in rows:
        sid, ra, dec = int(sid), float(ra), float(dec)
        miss12 += gaia.ang2pix(12, ra, dec) != sid >> 35
        miss8 += gaia.ang2pix(gaia.ORDER, ra, dec) != gaia.pixel_of(sid)
    n = len(rows)
    assert miss12 <= n // 20 and miss8 <= n // 50


def test_ang2pix_covers_all_faces():
    npix = 12 << (2 * gaia.ORDER)
    faces = set()
    for dec in np.arange(-89.5, 90, 1.0):
        for ra in np.arange(0.5, 360, 1.0):
            p = gaia.ang2pix(gaia.ORDER, ra, dec)
            assert 0 <= p < npix
            faces.add(p >> (2 * gaia.ORDER))
    assert len(faces) == 12


def test_disc_pixels_includes_center_and_neighbors():
    ps = gaia.disc_pixels(269.446, 4.7707, 0.2)
    assert gaia.ang2pix(gaia.ORDER, 269.446, 4.7707) in ps and 2 <= len(ps) <= 12


def fake_bulk(stars):
    """A gzip CSV shaped like a Gaia bulk file, and its name."""
    stars = sorted(stars, key=lambda s: s.source_id)
    lines = ["# %ECSV 1.0", "# ---",
             "solution_id,designation,source_id,random_index,ref_epoch,ra,ra_error,dec,dec_error,parallax,"
             "parallax_error,pm,pmra,pmra_error,pmdec,phot_g_mean_mag,extra"]
    for s in stars:
        pmra = "null" if math.isnan(s.pmra) else repr(s.pmra)
        lines.append(f'1,"Gaia DR3 {s.source_id}",{s.source_id},7,2016.0,{s.ra:.10f},0.1,{s.dec:.10f},0.1,'
                     f"{s.parallax!r},0.1,1,{pmra},0.1,{s.pmdec!r},{s.g!r},x")
    data = gzip.compress(("\n".join(lines) + "\n").encode())
    lo, hi = gaia.pixel_of(stars[0].source_id), gaia.pixel_of(stars[-1].source_id)
    return data, f"GaiaSource_{lo:06d}-{hi:06d}.csv.gz"


def test_cone_streams_tiles_once(fake_server, tmp_path):
    ra0, dec0 = 45.1, 0.2
    r = np.random.default_rng(12)
    stars = []
    for i in range(3000):
        ra = ra0 + (r.random() * 2 - 1) * 0.4
        dec = dec0 + (r.random() * 2 - 1) * 0.4
        pm = float(np.float32(r.standard_normal() * 10))
        if i % 7 == 0:
            pm = math.nan
        stars.append(gaia.Star((gaia.ang2pix(12, ra, dec) << 35) + i, ra, dec, 1.5, pm, -3.0,
                               float(np.float32(10 + r.random() * 10))))
    data, name = fake_bulk(stars)
    ranges = []

    def handler(path, q, h):
        if path == "/list":
            return 200, (f"<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>Gaia/gdr3/gaia_source/"
                         f"{name}</Key><Size>{len(data)}</Size></Contents><Contents><Key>Gaia/gdr3/gaia_source/"
                         f"_MD5SUM.txt</Key><Size>1</Size></Contents></ListBucketResult>").encode(), {}
        if path == "/files/" + name:
            ranges.append(h.get("Range"))
            return serve_range(data, h)
        return 404, b"", {}

    srv = fake_server(handler)
    s = gaia.Store(tmp_path, base=srv.url + "/files/", list_url=srv.url + "/list?prefix=x&delimiter=/",
                   chunk=4096)  # many chunks, to exercise the ordered parallel reader
    got = s.cone(ra0, dec0, 0.15, timeout=30)
    want = sum(_separation(ra0, dec0, st.ra, st.dec) <= 0.15 for st in stars)
    assert len(got) == want > 0
    assert any(math.isnan(st.pmra) for st in got), "null proper motions should read as NaN"
    assert all(st.parallax == 1.5 and st.pmdec == -3 for st in got), "columns mixed up"

    # Wait for the background stream to finish the file, then ask again.
    deadline = time.monotonic() + 30
    while not s.file_done(name):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    before = len(ranges)
    again = s.cone(ra0 + 0.2, dec0, 0.15, timeout=30)
    assert again and len(ranges) == before, "second cone downloaded again"
    assert (tmp_path / "index.json").exists()
    # A new store reads the index from disk.
    s2 = gaia.Store(tmp_path, base="http://127.0.0.1:9/", list_url="http://127.0.0.1:9/")
    assert s2.index()[0].name == name
    assert len(s2.cone(ra0, dec0, 0.15)) == want


def test_progress_reports_streams(tmp_path):
    s = gaia.Store(tmp_path)
    assert s.progress(10, 10, 0.15) == []


def test_live_barnard(tmp_path):
    """GAIA_LIVE=1 streams the real file around Barnard's Star from the ESA CDN."""
    if not os.environ.get("GAIA_LIVE"):
        pytest.skip("GAIA_LIVE not set")
    s = gaia.Store(os.environ.get("GAIA_DIR") or tmp_path)
    stars = s.cone(269.446, 4.7707, 0.15)
    assert any(st.source_id == 4472832130942575872 for st in stars)
