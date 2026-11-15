"""Fields built from real SPHEREx images and catalog sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .. import fits
from ..num import round_array
from ..wcs import Celestial, Wave
from .field import (CHANNELS, FLAG_MISSING, NUM_CHANNELS, PIX_SCALE, SUB_BANDS, Field, Frame, Visit,
                    field_size, stats)
from .grid import ARCSEC, WCS, ecliptic, separation
from .source import Source
from .targets import TARGETS

# Survey passes: within a pass a position is revisited over days to weeks,
# and passes are about six months apart.
SEASON_GAP = 40


class CutoutError(ValueError):
    pass


@dataclass
class ArchiveImage:
    """One spectral image covering the field, as listed by the archive."""

    path: str
    mjd: float
    detector: int
    exposure: str

    @classmethod
    def from_json(cls, d: dict) -> "ArchiveImage":
        return cls(path=str(d.get("path", "")), mjd=float(d.get("mjd", 0)),
                   detector=int(d.get("detector", 0)), exposure=str(d.get("exposure", "")))


def new_real_field(ra: float, dec: float, fov_arcmin: float, images: list[ArchiveImage], now_mjd: float) -> Field:
    """Plan a field from archive images. Each exposure covers the position with
    one pair of detectors (D1+D4, D2+D5 or D3+D6), so a visit has frames in two
    channels and the other four are unavailable."""
    n = field_size(fov_arcmin)
    f = Field(
        wcs=WCS(ra, dec, PIX_SCALE, n / 2, n / 2), n=n, fov=fov_arcmin, real=True,
        # Pixel values are MJy/sr; an aperture sum times the pixel solid angle
        # in sr is MJy, and 1e9 more gives mJy, the unit the archive tools use.
        flux_scale=(PIX_SCALE * ARCSEC) ** 2 * 1e9, flux_unit="mJy",
    )
    _, f.ecl_lat = ecliptic(ra, dec)

    by_id: dict[str, dict] = {}
    for im in images:
        if im.detector < 1 or im.detector > NUM_CHANNELS:
            continue
        e = by_id.get(im.exposure)
        if e is None:
            e = by_id[im.exposure] = {"mjd": im.mjd, "images": {}}
        e["mjd"] = min(e["mjd"], im.mjd)
        e["images"][im.detector - 1] = im
    exposures = sorted(by_id.values(), key=lambda e: e["mjd"])

    season = 0
    for v, e in enumerate(exposures):
        if v > 0 and e["mjd"] - exposures[v - 1]["mjd"] > SEASON_GAP:
            season += 1
        # The sub-band is only known once a frame arrives and its spectral WCS is read.
        f.visits.append(Visit(mjd=e["mjd"], season=season, sub_band=-1))
    for c in range(NUM_CHANNELS):
        f.frames[c] = []
        for v, e in enumerate(exposures):
            im = e["images"].get(c)
            f.frames[c].append(Frame(channel=c, visit=v, mjd=e["mjd"], available=im is not None,
                                     file=im.path if im else ""))

    for t in TARGETS:
        tra, tdec = t.source.position(now_mjd)
        if separation(ra, dec, tra, tdec) < fov_arcmin / 60:
            f.target_id, f.name = t.id, t.name
            break
    return f


def load_cutout(f: Field, fr: Frame, data: bytes) -> None:
    """Decode a cutout (as served by the proxy, without EPSF) and resample it
    onto the field grid. Cutouts come in detector orientation with SIP
    distortion, so every field pixel is looked up through the image WCS. The
    ZODI model is subtracted so backgrounds match between visits."""
    hdus = fits.parse(data)

    def get(name):
        h = fits.find(hdus, name)
        if h is None:
            raise CutoutError(f"cutout has no {name} extension")
        return h

    img_hdu = get("IMAGE")
    cel = Celestial(img_hdu)
    wave = Wave(img_hdu, hdus)
    img = img_hdu.image()
    h, w = img.shape

    def layer(name, read):
        hdu = fits.find(hdus, name)
        if hdu is None:
            return None
        try:
            return read(hdu)
        except fits.FitsError:
            return None

    flags = layer("FLAGS", fits.HDU.uint32_image)
    variance = layer("VARIANCE", fits.HDU.image)
    zodi = layer("ZODI", fits.HDU.image)
    if any(a is None or a.shape != (h, w) for a in (flags, variance, zodi)):
        raise CutoutError("cutout layers have different sizes")

    n = f.n
    jj, ii = np.mgrid[0:n, 0:n]
    ra, dec = f.wcs.to_sky_array(ii + 0.5, jj + 0.5)
    x, y, ok = cel.sky_to_pixel(ra, dec)
    x, y, ok = np.asarray(x), np.asarray(y), np.asarray(ok)
    xr, yr = round_array(x), round_array(y)
    inside = ok & (xr >= 0) & (yr >= 0) & (xr < w) & (yr < h)

    out = np.zeros((n, n), dtype=np.float32)
    out_var = np.zeros((n, n), dtype=np.float32)
    out_flags = np.full((n, n), FLAG_MISSING, dtype=np.uint32)
    xi = np.where(inside, xr, 0).astype(np.int64)
    yi = np.where(inside, yr, 0).astype(np.int64)
    out_flags[inside] = flags[yi[inside], xi[inside]]

    v, vok = bilinear(img, zodi, x, y, inside)
    out_flags[inside & ~vok] |= FLAG_MISSING
    out[vok] = v[vok]
    vv, vvok = bilinear(variance, None, x, y, vok)
    out_var[vvok] = vv[vvok]

    fr.image, fr.variance, fr.flags = out, out_var, out_flags
    fr.mjd = img_hdu.float("MJD-AVG", fr.mjd)

    def wave_at(ra_: float, dec_: float) -> float:
        px, py, _ = cel.sky_to_pixel(ra_, dec_)
        lam, _ = wave.at(px, py)
        return float(lam)

    fr.wave_at = wave_at
    fr.lambda_ = fr.lambda_at(f.wcs.ra, f.wcs.dec)
    fr.background, fr.sigma = stats(out, out_flags)
    fr.loaded = True

    # The pair of detectors in a visit sees the source through the same part of
    # their filters, so either frame tells which sub-band the visit is.
    vis = f.visits[fr.visit]
    if vis.sub_band < 0:
        ch = CHANNELS[fr.channel]
        vis.sub_band = max(0.0, min(SUB_BANDS - 1.0, (fr.lambda_ - ch.lo) / (ch.hi - ch.lo) * SUB_BANDS - 0.5))


def bilinear(a: np.ndarray, b: np.ndarray | None, x: np.ndarray, y: np.ndarray, where: np.ndarray):
    """Sample a - b (b may be None) at 0-based (x, y) where `where` is set,
    skipping non-finite pixels and reweighting the rest. Returns the values
    (float32) and a mask of the samples with enough weight."""
    h, w = a.shape
    x = np.where(where, x, 0.0)
    y = np.where(where, y, 0.0)
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    total = np.zeros(x.shape, dtype=np.float64)
    wsum = np.zeros(x.shape, dtype=np.float64)
    for dy in (0, 1):
        for dx in (0, 1):
            xi, yi = x0 + dx, y0 + dy
            inb = where & (xi >= 0) & (yi >= 0) & (xi < w) & (yi < h)
            xc, yc = np.where(inb, xi, 0), np.where(inb, yi, 0)
            v = a[yc, xc].astype(np.float64)
            if b is not None:
                v = v - b[yc, xc].astype(np.float64)
            use = inb & np.isfinite(v)
            wt = (1 - np.abs(dx - fx)) * (1 - np.abs(dy - fy))
            total += np.where(use, wt * np.where(use, v, 0.0), 0.0)
            wsum += np.where(use, wt, 0.0)
    good = where & (wsum >= 0.25)
    vals = np.where(good, total / np.where(good, wsum, 1.0), 0.0).astype(np.float32)
    return vals, good


@dataclass
class CatalogEntry:
    """A source from Gaia DR3 or CatWISE2020."""

    catalog: str
    name: str
    ra: float
    dec: float
    pmra: float  # mas/yr, includes cos(dec)
    pmdec: float  # mas/yr
    mjd: float  # epoch of the position
    mag: float  # Gaia G or WISE W2

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "CatalogEntry":
        return cls(catalog=str(d.get("catalog", "")), name=str(d.get("name", "")),
                   ra=float(d.get("ra", 0)), dec=float(d.get("dec", 0)),
                   pmra=float(d.get("pmra", 0)), pmdec=float(d.get("pmdec", 0)),
                   mjd=float(d.get("mjd", 0)), mag=float(d.get("mag", 0)))


def set_catalog(f: Field, entries: list[CatalogEntry]) -> None:
    """Replace the catalog sources of a real field and find the test object
    among them by its predicted position."""
    f.sources = []
    f.target = -1
    target = next((t.source for t in TARGETS if t.id == f.target_id), None)
    best = 5.0 / 3600  # degrees
    for e in entries:
        f.sources.append(Source(
            name=e.name, ra=e.ra, dec=e.dec, pmra=e.pmra, pmdec=e.pmdec, ref_mjd=e.mjd, catalog=True,
            catalog_name=e.catalog, catalog_mjd=e.mjd, catalog_mag=e.mag,
        ))
        if target is None:
            continue
        tra, tdec = target.position(e.mjd)
        d = separation(e.ra, e.dec, tra, tdec)
        if d < best:
            best = d
            f.target = len(f.sources) - 1
    if f.target >= 0:
        f.sources[f.target].name = f.name


