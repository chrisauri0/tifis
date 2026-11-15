"""Ports of internal/fits and internal/wcs tests."""

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from spherex import fits
from spherex.wcs import Celestial, Wave

DATA = Path(__file__).parent / "data"


def header(*cards):
    s = "".join(f"{c:<80}" for c in cards + ("END",))
    return (s + " " * (fits.padded(len(s)) - len(s))).encode()


def image(name, w, h):
    return fits.HDU(
        header("XTENSION= 'IMAGE   '", "BITPIX  =                  -32", "NAXIS   =                    2",
               f"NAXIS1  = {w:>20}", f"NAXIS2  = {h:>20}", "PCOUNT  =                    0",
               "GCOUNT  =                    1", f"EXTNAME = '{name:<8}'           / extension name"),
        b"\x01" * fits.padded(4 * w * h),
    )


def test_parse_and_join():
    primary = fits.HDU(header("SIMPLE  =                    T", "BITPIX  =                    8",
                              "NAXIS   =                    0", "VERSION = '7.0.5   '"))
    hdus = fits.parse(fits.join([primary, image("IMAGE", 58, 59), image("EPSF", 300, 400), image("ZODI", 58, 59)]))
    assert ",".join(h.name() for h in hdus) == "PRIMARY,IMAGE,EPSF,ZODI"
    assert hdus[0].keyword("VERSION") == "7.0.5"
    assert len(hdus[2].data) == fits.padded(4 * 300 * 400)


def test_truncated():
    data = fits.join([fits.HDU(header("SIMPLE  =                    T", "BITPIX  =                    8",
                                      "NAXIS   =                    0")), image("IMAGE", 58, 59)])
    with pytest.raises(fits.FitsError):
        fits.parse(data[: len(data) - fits.BLOCK])
    with pytest.raises(fits.FitsError):
        fits.parse(b"not a fits file" * 300)


def test_keywords_and_numbers():
    h = fits.HDU(header("A       =               1.5D+2 / Fortran exponent", "B       = 'x / y   ' / slash in string",
                        "C       =                   12", "MSKN0001= 'OVERFLOW'", "MSKN0002= 'HOT     '"))
    assert h.float("A", 0) == 150
    assert h.keyword("B") == "x / y"
    assert h.int("C", 0) == 12 and h.int("missing", 7) == 7 and h.float("B", -1) == -1
    assert h.keywords("MSKN") == {"MSKN0001": "OVERFLOW", "MSKN0002": "HOT"}


def test_real_cutout_layers():
    hdus = fits.parse((DATA / "barnard_d6.fits").read_bytes())
    names = [h.name() for h in hdus]
    assert names[:2] == ["PRIMARY", "IMAGE"] and "EPSF" not in names
    img = fits.find(hdus, "IMAGE").image()
    flags = fits.find(hdus, "FLAGS").uint32_image()
    assert img.shape == flags.shape and img.dtype == np.float32 and flags.dtype == np.uint32
    path = os.environ.get("SPHEREX_CUTOUT")
    if path:  # SPHEREX_CUTOUT=/path/to/cutout.fits checks a real IRSA cutout
        for h in fits.parse(Path(path).read_bytes()):
            print(f"{h.name():<8} {len(h.data):8d} bytes")


@pytest.fixture(scope="module")
def cutout():
    hdus = fits.parse((DATA / "barnard_d6.fits").read_bytes())
    return fits.find(hdus, "IMAGE"), hdus


@pytest.fixture(scope="module")
def reference():
    return json.loads((DATA / "astropy_reference.json").read_text())


def test_celestial_matches_astropy(cutout, reference):
    img, _ = cutout
    c = Celestial(img)
    for x, y, ra_ref, dec_ref in reference["pixel_to_world"]:
        ra, dec = c.pixel_to_sky(x, y)
        dra = (ra - ra_ref) * math.cos(math.radians(dec)) * 3600
        assert math.hypot(dra, (dec - dec_ref) * 3600) <= 0.01
    for ra, dec, x_ref, y_ref in reference["world_to_pixel"]:
        x, y, ok = c.sky_to_pixel(ra, dec)
        assert ok and math.hypot(x - x_ref, y - y_ref) <= 0.001
    # Arrays give the same answers as scalars.
    p = np.array(reference["world_to_pixel"])
    xs, ys, oks = c.sky_to_pixel(p[:, 0], p[:, 1])
    assert oks.all()
    np.testing.assert_allclose(np.hypot(xs - p[:, 2], ys - p[:, 3]), 0, atol=0.001)


def test_far_side_is_not_ok(cutout):
    c = Celestial(cutout[0])
    ra0, dec0 = c.crval
    _, _, ok = c.sky_to_pixel(ra0 + 180, -dec0)
    assert not ok


def test_wave_matches_astropy(cutout, reference):
    img, hdus = cutout
    w = Wave(img, hdus)
    for x, y, lam, bw in reference["wave"]:
        l, b = w.at(x, y)
        assert abs(l - lam) <= 1e-5 and abs(b - bw) <= 1e-6


def test_astropy_cross_check(cutout):
    """With astropy installed, compare directly against it on a grid."""
    astropy_wcs = pytest.importorskip("astropy.wcs")
    from astropy.io import fits as afits

    img, _ = cutout
    with afits.open(DATA / "barnard_d6.fits") as hdul:
        ref = astropy_wcs.WCS(hdul["IMAGE"].header)
        ys, xs = np.mgrid[0:60:7, 0:60:7].astype(float)
        ra_ref, dec_ref = ref.all_pix2world(xs, ys, 0)
        ra, dec = Celestial(img).pixel_to_sky(xs, ys)
        d = np.hypot((ra - ra_ref) * np.cos(np.radians(dec_ref)), dec - dec_ref) * 3600
        assert d.max() < 0.01
