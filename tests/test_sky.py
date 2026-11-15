"""Ports of internal/sky tests, plus checks of the simulation and composition helpers."""

import math
from pathlib import Path

import numpy as np
import pytest

from spherex import sky

DATA = Path(__file__).parent / "data"
TEST_NOW = 61356  # 2026-11-12


def test_wcs_round_trip():
    w = sky.WCS(269.45, 4.69, sky.PIX_SCALE, 30, 30)
    ra, dec = w.to_sky(12.3, 47.9)
    x, y = w.to_pixel(ra, dec)
    assert abs(x - 12.3) < 1e-6 and abs(y - 47.9) < 1e-6
    # North is up (smaller y) and east is left (smaller x).
    assert w.to_pixel(269.45, 4.70)[1] < 30
    assert w.to_pixel(269.46, 4.69)[0] < 30
    assert w.to_sky(30, 30) == (269.45, 4.69)


@pytest.fixture(scope="module")
def barnard_field():
    src = sky.TARGETS[0].source
    ra, dec = src.position(TEST_NOW)
    return sky.new_field(ra, dec, 6, TEST_NOW)


def test_schedule_has_seasons(barnard_field):
    f = barnard_field
    assert len(f.visits) >= 34, "expected at least two seasons of visits"
    assert f.visits[-1].season + 1 >= 3, "expected 3+ seasons by Nov 2026"
    assert f.target_id == "barnard"
    assert all(a.mjd <= b.mjd for a, b in zip(f.visits, f.visits[1:]))
    assert all(v.mjd >= sky.field.SURVEY_START_MJD and v.mjd <= TEST_NOW - 7 for v in f.visits)


def test_simulation_is_deterministic(barnard_field):
    src = sky.TARGETS[0].source
    g = sky.new_field(*src.position(TEST_NOW), 6, TEST_NOW)
    assert [v.mjd for v in g.visits] == [v.mjd for v in barnard_field.visits]
    a, b = barnard_field.frames[2][3], g.frames[2][3]
    a.loaded = b.loaded = False
    a.available = b.available = True
    barnard_field.load(a)
    g.load(b)
    np.testing.assert_array_equal(a.image, b.image)
    np.testing.assert_array_equal(a.flags, b.flags)


def test_track_recovers_barnard_motion():
    src = sky.TARGETS[0].source
    f = sky.new_field(*src.position(TEST_NOW), 6, TEST_NOW)
    ch = 2
    for fr in f.frames[ch]:
        f.load(fr)
    v = next(i for i, fr in enumerate(f.frames[ch]) if fr.available)
    x, y = f.wcs.to_pixel(*src.position(f.visits[v].mjd))
    m = sky.track(f, ch, v, x, y)
    assert m.moving, f"Barnard's Star should be moving; {len(m.points)} points"
    pm_ra, pm_dec = m.proper_motion()
    assert abs(pm_dec - 10.36) <= 0.8 and abs(pm_ra + 0.80) <= 0.8
    meas = sky.measure(f, m)
    assert meas and all(x.channel == ch for x in meas)


def test_wise0855_is_invisible_short_and_bright_long():
    src = sky.TARGETS[2].source
    assert src.flux_at(1.0, TEST_NOW) / src.flux_at(4.7, TEST_NOW) <= 1e-3


def test_real_field_groups_exposures():
    images = [
        sky.ArchiveImage("a1", 60902.10, 1, "A"), sky.ArchiveImage("a4", 60902.11, 4, "A"),
        sky.ArchiveImage("b3", 60905.00, 3, "B"), sky.ArchiveImage("b6", 60905.00, 6, "B"),
        sky.ArchiveImage("c2", 61090.00, 2, "C"),
    ]
    f = sky.new_real_field(10, 10, 6, images, TEST_NOW)
    assert len(f.visits) == 3
    assert f.visits[1].season == 0 and f.visits[2].season == 1
    assert f.frames[0][0].available and f.frames[3][0].available and not f.frames[1][0].available
    assert f.frames[0][0].file == "a1" and f.visits[0].sub_band == -1


def test_load_real_cutout():
    data = (DATA / "barnard_d6.fits").read_bytes()
    barnard = sky.TARGETS[0].source
    ra, dec = barnard.position(TEST_NOW)
    f = sky.new_real_field(ra, dec, 6, [sky.ArchiveImage(
        "ibe/data/spherex/x/level2_2025W33_2C_0321_1D6_spx.fits", 60902.8647, 6, "2025W33_2C_0321_1")], TEST_NOW)
    assert f.target_id == "barnard" and len(f.visits) == 1
    assert f.frames[5][0].available and not f.frames[2][0].available
    fr = f.frames[5][0]
    sky.load_cutout(f, fr, data)
    assert abs(fr.lambda_ - 4.93) <= 0.02
    assert 14 <= f.visits[0].sub_band <= 16.5
    # The star should be where its proper motion puts it on the observation date.
    x, y = f.wcs.to_pixel(*barnard.position(fr.mjd))
    cx, cy, snr = sky.centroid(fr, f.n, x, y, 2)
    assert snr >= 20 and math.hypot(cx - x, cy - y) <= 0.7
    # Its core is saturated and flagged, so the measurement must say so.
    flux, ferr, ok = sky.aperture(fr, f.n, cx, cy)
    assert not ok and flux > 0 and ferr > 0


def test_load_cutout_rejects_bad_files():
    f = sky.new_real_field(10, 10, 6, [sky.ArchiveImage("x", 60000, 1, "A")], TEST_NOW)
    with pytest.raises(Exception):
        sky.load_cutout(f, f.frames[0][0], b"SIMPLE  =" + b" " * 3000)


def test_set_catalog_finds_target():
    barnard = sky.TARGETS[0].source
    ra, dec = barnard.position(TEST_NOW)
    f = sky.new_real_field(ra, dec, 6, [], TEST_NOW)
    gra, gdec = barnard.position(sky.GAIA_EPOCH)
    f.name = "Barnard's Star"
    sky.set_catalog(f, [
        sky.CatalogEntry("Gaia DR3", "Gaia DR3 1", ra + 0.01, dec, 0, 0, sky.GAIA_EPOCH, 12),
        sky.CatalogEntry("Gaia DR3", "Gaia DR3 4472832130942575872", gra, gdec, -801.551, 10362.394, sky.GAIA_EPOCH, 8.2),
    ])
    assert f.target == 1 and f.sources[1].name == "Barnard's Star" and len(f.sources) == 2


def test_stats_and_percentile_ignore_bad_pixels():
    img = np.arange(16, dtype=np.float32).reshape(4, 4)
    flags = np.zeros((4, 4), dtype=np.uint32)
    flags[3, :] = sky.FLAG_HOT
    med, sig = sky.stats(img, flags)
    assert med == 6.0  # upper median of 0..11
    assert sig == pytest.approx(1.4826 * 3)
    assert sky.percentile(img, flags, 1.0) == 11.0
    assert sky.stats(img, np.full((4, 4), sky.FLAG_HOT, np.uint32)) == (0.0, 1.0)


def test_subtract_plane_removes_a_tilt():
    n = 40
    ys, xs = np.mgrid[0:n, 0:n]
    img = (1.0 + 0.01 * xs - 0.02 * ys).astype(np.float32)
    img[20, 20] += 50  # a source, ignored by the clipping
    sky.subtract_plane(img, None, n, 0.01)
    img[20, 20] -= 50
    assert np.abs(img).max() < 1e-5


def test_flag_names():
    assert sky.flag_names(sky.FLAG_HOT | sky.FLAG_NONLINEAR | 1 << 21) == ["HOT", "NONLINEAR"]
    assert sky.flag_names(0) == []
