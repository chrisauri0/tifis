"""The Python port against values computed by the original Go code.

tests/data/go_reference_*.json were produced by the Go implementation this
package replaces (internal/sky, internal/gaia, internal/irsa) on the same
inputs, so these tests pin the port to it number by number.
"""

import base64
import json
import math
from pathlib import Path

import numpy as np
import pytest

from spherex import gaia, irsa, sky
from spherex.num import go_round

DATA = Path(__file__).parent / "data"


def load(name):
    return json.loads((DATA / f"go_reference_{name}.json").read_text())


def f32(b64, n):
    return np.frombuffer(base64.b64decode(b64), dtype="<f4").reshape(n, n)


def u32(b64, n):
    return np.frombuffer(base64.b64decode(b64), dtype="<u4").reshape(n, n)


@pytest.fixture(scope="module")
def ref():
    return load("sky")


@pytest.fixture(scope="module")
def real_frame(ref):
    data = (DATA / "barnard_d6.fits").read_bytes()
    ra, dec = ref["field"]["ra"], ref["field"]["dec"]
    f = sky.new_real_field(ra, dec, 6, [sky.ArchiveImage(
        "ibe/data/spherex/x/level2_2025W33_2C_0321_1D6_spx.fits", 60902.8647, 6, "2025W33_2C_0321_1")], 61356)
    fr = f.frames[5][0]
    sky.load_cutout(f, fr, data)
    return f, fr


def test_round_matches_go(ref):
    barnard = sky.TARGETS[0].source
    ra, dec = barnard.position(61356)
    assert go_round(ra * 2000) / 2000 == ref["field"]["ra"]
    assert go_round(dec * 2000) / 2000 == ref["field"]["dec"]


def test_reprojection_matches_go(ref, real_frame):
    f, fr = real_frame
    n = ref["field"]["n"]
    assert f.n == n and f.target_id == ref["field"]["target"]
    assert f.flux_scale == pytest.approx(ref["field"]["fluxScale"], rel=1e-15)
    g = ref["frame"]
    np.testing.assert_array_equal(fr.flags, u32(g["flags"], n))
    np.testing.assert_allclose(fr.image, f32(g["image"], n), rtol=2e-6, atol=2e-7)
    np.testing.assert_allclose(fr.variance, f32(g["variance"], n), rtol=2e-6, atol=1e-9)
    assert fr.lambda_ == pytest.approx(g["lambda"], abs=1e-9)
    assert fr.mjd == g["mjd"]
    assert fr.background == pytest.approx(g["bg"], rel=1e-6)
    assert fr.sigma == pytest.approx(g["sigma"], rel=1e-5)
    assert f.visits[0].sub_band == pytest.approx(g["subband"], abs=1e-7)
    assert sky.percentile(fr.image, fr.flags, 0.998) == pytest.approx(g["p998"], rel=1e-6)


def test_photometry_matches_go(ref, real_frame):
    f, fr = real_frame
    p = ref["phot"]
    barnard = sky.TARGETS[0].source
    x, y = f.wcs.to_pixel(*barnard.position(fr.mjd))
    assert (x, y) == pytest.approx(p["pred"], abs=1e-9)
    cx, cy, snr = sky.centroid(fr, f.n, x, y, 2)
    assert (cx, cy) == pytest.approx(p["centroid"][:2], abs=1e-6)
    assert snr == pytest.approx(p["centroid"][2], rel=1e-5)
    flux, err, good, npix = sky.aperture_full(fr, f.n, cx, cy)
    assert flux == pytest.approx(p["aperture"][0], rel=1e-5)
    assert err == pytest.approx(p["aperture"][1], rel=1e-5)
    assert (good, npix) == (p["aperture"][2], p["aperture"][3])
    for x, y, outer, inner in p["localBackground"]:
        assert sky.local_background(fr, f.n, x, y, sky.ANNULUS_INNER, sky.ANNULUS_OUTER) == pytest.approx(outer, rel=1e-6)
        assert sky.local_background(fr, f.n, x, y, sky.CENTROID_INNER, sky.CENTROID_OUTER) == pytest.approx(inner, rel=1e-6)
    for x, y, lam in p["lambdaAt"]:
        assert fr.lambda_at(*f.wcs.to_sky(x, y)) == pytest.approx(lam, abs=1e-9)
    m = sky.Motion(x0=cx, y0=cy, t0=fr.mjd)
    got = [x.to_json() for x in sky.measure(f, m)]
    want = ref["measure"]
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert (g["c"], g["v"], g["ok"]) == (w["c"], w["v"], w["ok"])
        for k in "tlfe":
            assert g[k] == pytest.approx(w[k], rel=1e-5)


def test_plane_and_stats_match_go(ref, real_frame):
    f, fr = real_frame
    img = fr.image.copy()
    sky.subtract_plane(img, fr.flags, f.n, fr.sigma * math.sqrt(2))
    np.testing.assert_allclose(img, f32(ref["plane"], f.n), rtol=1e-5, atol=2e-6)
    med, sig = sky.stats(fr.image, None)
    assert (med, sig) == pytest.approx(ref["statsNoFlags"], rel=1e-6)


def test_geometry_matches_go(ref):
    for ra, dec, lon, lat, b in ref["geo"]:
        assert sky.ecliptic(ra, dec) == pytest.approx((lon, lat), abs=1e-9)
        assert sky.galactic_latitude(ra, dec) == pytest.approx(b, abs=1e-9)
    for mjd, lon in ref["sun"]:
        assert sky.sun_longitude(mjd) == pytest.approx(lon, abs=1e-9)
    w = sky.WCS(269.45, 4.69, sky.PIX_SCALE, 29.5, 29.5)
    for x, y, ra, dec, xx, yy in ref["grid"]:
        assert w.to_sky(x, y) == pytest.approx((ra, dec), abs=1e-11)
        assert w.to_pixel(ra, dec) == pytest.approx((xx, yy), abs=1e-7)
        ra_a, dec_a = w.to_sky_array(np.array([x]), np.array([y]))
        assert (ra_a[0], dec_a[0]) == pytest.approx((ra, dec), abs=1e-11)
    for i, lam, mjd, flux in ref["flux"]:
        assert sky.TARGETS[int(i)].source.flux_at(lam, mjd) == pytest.approx(flux, rel=1e-9, abs=1e-300)
    for i, ra, dec in ref["positions"]:
        assert sky.TARGETS[int(i)].source.position(61356) == pytest.approx((ra, dec), abs=1e-12)


def test_dates_flags_hash_match_go(ref):
    for mjd, iso, year, week, yday in ref["dates"]:
        d = sky.mjd_to_date(mjd)
        assert d.isoformat() == iso
        assert d.isocalendar()[:2] == (year, week)
        assert d.timetuple().tm_yday == yday
    assert sky.flag_names(sky.BAD_MASK | 1 << 21) == ref["names"]
    assert sky.BAD_MASK == ref["badMask"]
    assert [sky.hash_string("barnard"), sky.hash_string("269.4461 4.7707")] == ref["hash"]


def test_healpix_matches_go():
    ref = load("gaia")
    for ra, dec, p8, p12, p3 in ref["pix"]:
        assert gaia.ang2pix(8, ra, dec) == p8
        assert gaia.ang2pix(12, ra, dec) == p12
        assert gaia.ang2pix(3, ra, dec) == p3
    for d in ref["discs"]:
        assert sorted(gaia.disc_pixels(*d["c"])) == d["p"]


def test_gaia_rows_match_go():
    ref = load("gaia")
    header = (b"solution_id,designation,source_id,random_index,ref_epoch,ra,ra_error,dec,dec_error,"
              b"parallax,parallax_error,pm,pmra,pmra_error,pmdec,phot_g_mean_mag,extra")
    cols = gaia.store.columns(header)
    assert cols == ref["cols"]
    for row in ref["rows"]:
        star = gaia.store.parse_row(row["line"].encode(), cols)
        assert (star is not None) == row["ok"], row["line"]
        if star is None:
            continue
        assert star.source_id == row["id"]
        assert (star.ra, star.dec) == (row["ra"], row["dec"])
        for k, v in (("parallax", "plx"), ("pmra", "pmra"), ("pmdec", "pmdec"), ("g", "g")):
            got = getattr(star, k)
            if row[v] == "NaN":
                assert math.isnan(got)
            else:
                assert got == pytest.approx(row[v], rel=1e-7)


def test_visits_and_merge_match_go():
    ref = load("irsa")
    got = [v.to_json() for v in irsa.visits_from_rows(ref["rows"])]
    assert got == ref["visits"]
    merged = irsa.merge(
        [sky.CatalogEntry("Gaia DR3", "g1", 133.7847, -7.2442, 0, 0, sky.GAIA_EPOCH, 12),
         sky.CatalogEntry("Gaia DR3", "g2", 10, 10, 100, -50, sky.GAIA_EPOCH, 9)],
        [sky.CatalogEntry("CatWISE2020", "c1", 133.78478, -7.24421, 0, 0, 57170, 15),
         sky.CatalogEntry("CatWISE2020", "c2", 133.79, -7.25, 0, 0, 57170, 14),
         sky.CatalogEntry("CatWISE2020", "c3", 133.7901, -7.2501, 0, 0, 57170, 14.5),
         sky.CatalogEntry("CatWISE2020", "c4", 10.00005, 9.99997, 0, 0, 57170, 9.5)])
    assert [e.to_json() for e in merged] == ref["merged"]
