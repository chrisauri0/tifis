"""Ports of internal/irsa tests."""

import math
import os
import threading
import time
from pathlib import Path

import pytest

from spherex import fits, irsa, sky

TAP_CSV = b"""uri,time_bounds_lower,energy_bandpassname
ibe/data/spherex/qr3/level2/2025W33_2C/l2b-v27-2026-228/6/level2_2025W33_2C_0321_1D6_spx_l2b-v27-2026-228.fits,60902.864715,SPHEREx-D6
ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27-2026-228/6/level2_2025W33_2C_0321_1D6_spx_l2b-v27-2026-228.fits,60902.864715,SPHEREx-D6
ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27-2026-228/3/level2_2025W33_2C_0321_1D3_spx_l2b-v27-2026-228.fits,60902.864715,SPHEREx-D3
ibe/data/spherex/dr1/level2/2025W21_2C/l2b-v27-2026-199/2/level2_2025W21_2C_0401_4D2_spx_l2b-v27-2026-199.fits,60800.5,SPHEREx-D2
"""

SIA_VOTABLE = b"""<?xml version="1.0" encoding="utf-8"?>
<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
 <RESOURCE type="meta"><TABLE><FIELD name="ignored"/></TABLE></RESOURCE>
 <RESOURCE type="results"><TABLE>
  <FIELD name="s_ra"/><FIELD name="access_url"/><FIELD name="t_min"/>
  <DATA><TABLEDATA>
   <TR><TD>270.1</TD><TD>https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W33_2A/l2b-v27-2026-241/3/level2_2026W33_2A_0594_4D3_spx_l2b-v27-2026-241.fits</TD><TD>61268.630812</TD></TR>
   <TR><TD>270.1</TD><TD>https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27-2026-228/6/level2_2025W33_2C_0321_1D6_spx_l2b-v27-2026-228.fits</TD><TD>60902.864715</TD></TR>
  </TABLEDATA></DATA>
 </TABLE></RESOURCE>
</VOTABLE>"""


def test_parse_visits():
    v = irsa.parse_visits(TAP_CSV)
    assert len(v) == 3, "the qr3 duplicate should be dropped"
    assert v[0].detector == 2 and v[0].exposure == "2025W21_2C_0401_4"
    assert all(x.release == "dr1" for x in v if x.detector == 6)
    with pytest.raises(irsa.IrsaError):
        irsa.parse_visits(b"<VOTABLE>error</VOTABLE>")


def test_valid_path():
    cases = {
        "ibe/data/spherex/dr1/level2/x/1/level2_x.fits": True,
        "ibe/data/spherex/../../etc/passwd.fits": False,
        "ibe/data/wise/allwise/x.fits": False,
        "ibe/data/spherex/x.fits?center=1": False,
        "https://evil.example/ibe/data/spherex/x.fits": False,
    }
    for p, want in cases.items():
        assert irsa.valid_path(p) == want, p


def fake_cutout() -> bytes:
    def card(*cards):
        s = "".join(f"{c:<80}" for c in cards + ("END",))
        return (s + " " * ((len(s) + 2879) // 2880 * 2880 - len(s))).encode()

    def img(name, n):
        return fits.HDU(card("XTENSION= 'IMAGE   '", "BITPIX  =                    8", "NAXIS   =                    1",
                             f"NAXIS1  = {n:>20}", f"EXTNAME = '{name}'"), bytes((n + 2879) // 2880 * 2880))

    return fits.join([fits.HDU(card("SIMPLE  =                    T", "BITPIX  =                    8",
                                    "NAXIS   =                    0")),
                      img("IMAGE", 100), img("FLAGS", 100), img("EPSF", 50000), img("WCS-WAVE", 720)])


def test_cutout_drops_psf_and_retries(fake_server):
    calls = []

    def handler(path, q, h):
        calls.append(q)
        if len(calls) == 1:
            return 503, b"busy", {}
        assert q["center"] == ["269.446080,4.770690d"]
        return 200, fake_cutout(), {}

    srv = fake_server(handler)
    data = irsa.Client(srv.url, 2).cutout("ibe/data/spherex/dr1/level2/x/6/level2_x.fits", 269.44608, 4.77069, 0.1)
    assert ",".join(h.name() for h in fits.parse(data)) == "PRIMARY,IMAGE,FLAGS,WCS-WAVE"
    assert len(calls) == 2


def test_cutout_does_not_retry_client_errors(fake_server):
    srv = fake_server(lambda p, q, h: (404, b"not found", {}))
    with pytest.raises(irsa.IrsaError):
        irsa.Client(srv.url, 2).cutout("ibe/data/spherex/x.fits", 1, 1, 0.1)
    assert len(srv.calls) == 1


def test_cutout_rejects_other_paths():
    with pytest.raises(irsa.IrsaError):
        irsa.Client("http://127.0.0.1:9", 2).cutout("ibe/data/wise/x.fits", 1, 1, 0.1)


def test_cache_merges_concurrent_requests(tmp_path):
    c = irsa.Cache(tmp_path)
    fetches = []
    release = threading.Event()

    def fetch():
        fetches.append(1)
        release.wait()
        return b"visits"

    results = []
    threads = [threading.Thread(target=lambda: results.append(c.get("k", 3600, fetch))) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join()
    assert len(fetches) == 1
    assert all(data == b"visits" for data, _ in results)
    assert c.get("k", 3600, fetch)[1], "second read should hit the disk cache"
    time.sleep(0.01)
    assert not c.get("k", 1e-9, lambda: b"new")[1], "expired entry should be fetched again"
    assert c.lookup("k", 0) == b"new"


def test_cache_does_not_store_errors(tmp_path):
    c = irsa.Cache(tmp_path)

    def boom():
        raise OSError("down")

    with pytest.raises(OSError):
        c.get("k", 0, boom)
    assert c.lookup("k", 0) is None
    assert not [p for p in Path(tmp_path).rglob(".tmp-*")]


def test_visits_sia(fake_server):
    def handler(path, q, h):
        assert path == "/SIA" and len(q["COLLECTION"]) == 2
        return 200, SIA_VOTABLE, {}

    srv = fake_server(handler)
    v = irsa.Client(srv.url, 2).visits_sia(269.45, 4.77)
    assert len(v) == 2 and v[0].detector == 6 and v[0].exposure == "2025W33_2C_0321_1" and v[1].release == "qr3"
    assert v[0].path == ("ibe/data/spherex/dr1/level2/2025W33_2C/l2b-v27-2026-228/6/"
                         "level2_2025W33_2C_0321_1D6_spx_l2b-v27-2026-228.fits")
    path = os.environ.get("SPHEREX_SIA")
    if path:  # SPHEREX_SIA=/path/to/response.xml checks a saved IRSA SIA answer
        print(len(irsa.visits_from_rows(irsa.votable_columns(Path(path).read_bytes(), "access_url", "t_min"))))


def test_visits_tap(fake_server):
    def handler(path, q, h):
        assert path == "/TAP/sync" and "spherex.artifact" in q["QUERY"][0] and q["FORMAT"] == ["csv"]
        return 200, TAP_CSV, {}

    srv = fake_server(handler)
    assert len(irsa.Client(srv.url, 2).visits_tap(269.45, 4.77)) == 3


def test_catwise_and_merge(fake_server):
    def handler(path, q, h):
        if "catwise_2020" not in q["QUERY"][0]:
            return 400, b"unexpected query", {}
        # Barnard's Star (also in Gaia) and WISE 0855 split in two entries.
        return 200, (b"source_name,ra,dec,pmra,pmdec,w2mpro\n"
                     b"J175747.66+044419.7,269.4485837,4.7376900,-0.80,10.36,4.1\n"
                     b"J085507.96-071439.3,133.7831722,-7.2442516,-8.02120,1.03570,15.787\n"
                     b"J085508.34-071439.2,133.7847613,-7.2442498,-7.96500,0.80620,15.721\n"), {}

    srv = fake_server(handler)
    cw = irsa.Client(srv.url, 2).catwise(269.45, 4.77, 0.15)
    assert len(cw) == 3 and abs(cw[2].pmra + 7965) <= 0.5 and cw[0].mjd == irsa.CATWISE_EPOCH_MJD
    g = [sky.CatalogEntry("Gaia DR3", "Gaia DR3 4472832130942575872", 269.44850252544, 4.73942005111,
                          -801.551, 10362.394, sky.GAIA_EPOCH, 8.19)]
    got = irsa.merge(g, cw)
    assert len(got) == 2 and got[0].catalog == "Gaia DR3" and "J085508.34" in got[1].name


def test_num():
    assert irsa.num(" 1.5 ") == 1.5 and irsa.num("") == 0 and irsa.num("nan") == 0 and irsa.num("x") == 0
    assert math.isinf(irsa.num("inf"))
