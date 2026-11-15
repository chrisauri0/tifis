"""The field model: channels, flags, visits, frames, and the simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..num import go_round
from .grid import DEG, MJD_J2000, WCS, ecliptic, galactic_latitude, mjd_to_date, separation, sun_longitude
from .rand import MASK64, hash_string, new_rand
from .source import SED_STAR, Source, flux_from_mag
from .targets import TARGETS

try:  # scipy is optional; it only speeds up the simulation.
    from scipy.special import erf as _erf
except ImportError:  # pragma: no cover - depends on the environment
    _erf = np.vectorize(math.erf, otypes=[np.float64])

NUM_CHANNELS = 6
# The linear variable filters split each detector into 17 spectral channels,
# so every visit sees a source at a different wavelength.
SUB_BANDS = 17
PIX_SCALE = 6.15  # arcsec per pixel
SATURATION = 800  # image units; pixels above it are flagged NONLINEAR

SURVEY_START_MJD = 60796  # 2025-05-01
PROCESSING_DAYS = 7
STAR_BOX_ARCMIN = 13


@dataclass(frozen=True)
class Channel:
    lo: float  # µm
    hi: float
    sigma: float  # pixel noise, image units
    fwhm: float  # pixels
    zodi: float  # typical background, image units

    def lambda_(self, sub: float) -> float:
        return self.lo + (sub + 0.5) / SUB_BANDS * (self.hi - self.lo)


CHANNELS = (
    Channel(0.75, 1.10, 0.004, 1.7, 0.12),
    Channel(1.10, 1.60, 0.004, 1.7, 0.10),
    Channel(1.60, 2.40, 0.004, 1.8, 0.07),
    Channel(2.40, 3.80, 0.005, 1.9, 0.05),
    Channel(3.80, 4.40, 0.008, 2.0, 0.09),
    Channel(4.40, 5.00, 0.010, 2.1, 0.14),
)

# The SPHEREx FLAGS bitmask; bit n is named by keyword MSKNnnnn in the FLAGS
# header of every spectral image.
FLAG_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "NONFUNC": 6, "DICHROIC": 7,
    "MISSING_DATA": 9, "HOT": 10, "COLD": 11, "FULLSAMPLE": 12, "PHANMISS": 14,
    "NONLINEAR": 15, "PERSIST": 17, "OUTLIER": 19, "CROSSTALK": 20, "SOURCE": 21,
    "GHOST": 22, "GHOST_FPA": 23, "GHOST_EXT": 24, "STREAK": 25, "BLOOM": 26,
    "SNOWBALL": 27, "HALO": 28,
}
FLAG_TRANSIENT = 1 << 0
FLAG_MISSING = 1 << 9
FLAG_HOT = 1 << 10
FLAG_NONLINEAR = 1 << 15

# Flags that make a pixel unreliable for photometry: the list the SPHEREx
# Source Discovery Tool uses for its CONTAINS_BAD_PIXEL warning. SOURCE,
# FULLSAMPLE, PHANMISS and OUTLIER are informational and not included.
BAD_MASK = 0
for _n in ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "DICHROIC", "MISSING_DATA", "HOT", "COLD",
           "NONLINEAR", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT", "STREAK", "PERSIST", "BLOOM",
           "SNOWBALL", "HALO"):
    BAD_MASK |= 1 << FLAG_BITS[_n]
BAD_MASK_NO_NONLINEAR = BAD_MASK & ~FLAG_NONLINEAR


def flag_bad(f: int) -> bool:
    """Whether a pixel should be left out of measurements. Saturated pixels
    still carry signal, so callers that want them mask NONLINEAR out."""
    return f & BAD_MASK != 0


def bad(flags: np.ndarray, mask: int = BAD_MASK) -> np.ndarray:
    return (flags & np.uint32(mask)) != 0


def flag_names(f: int) -> list[str]:
    """The problem flags set in f, sorted."""
    return sorted(name for name, bit in FLAG_BITS.items() if f & BAD_MASK & (1 << bit))


@dataclass
class Visit:
    """One pointing that covers the field."""

    mjd: float
    season: int
    sub_band: float


@dataclass(eq=False)
class Frame:
    channel: int
    visit: int
    mjd: float
    lambda_: float = 0.0  # µm at the field center
    available: bool = False
    loaded: bool = False
    file: str = ""  # archive path for real data
    image: np.ndarray | None = None  # (n, n) float32
    variance: np.ndarray | None = None  # None for simulated frames
    flags: np.ndarray | None = None  # (n, n) uint32
    background: float = 0.0
    sigma: float = 0.0
    # Wavelength at a sky position; with the linear variable filters it
    # changes across the frame. None means lambda_ everywhere.
    wave_at: Callable[[float, float], float] | None = None

    def lambda_at(self, ra: float, dec: float) -> float:
        if self.wave_at is None:
            return self.lambda_
        return self.wave_at(ra, dec)


@dataclass(eq=False)
class Field:
    wcs: WCS
    n: int
    fov: float  # arcmin
    name: str = ""
    target_id: str = ""
    visits: list[Visit] = field(default_factory=list)
    frames: list[list[Frame]] = field(default_factory=lambda: [[] for _ in range(NUM_CHANNELS)])
    sources: list[Source] = field(default_factory=list)
    target: int = -1  # index in sources
    ecl_lat: float = 0.0
    real: bool = False
    # Turns an aperture sum of pixel values into flux_unit.
    flux_scale: float = 1.0
    flux_unit: str = ""
    seed: int = 0

    def load(self, fr: Frame) -> None:
        load_simulated(self, fr)


def field_size(fov_arcmin: float) -> int:
    return max(16, int(go_round(fov_arcmin * 60 / PIX_SCALE)))


def new_field(ra: float, dec: float, fov_arcmin: float, now_mjd: float) -> Field:
    """Plan a simulated cutout: which visits cover the position, at which
    wavelengths, and what is in the sky. Pixels are produced later by load."""
    n = field_size(fov_arcmin)
    f = Field(
        wcs=WCS(ra, dec, PIX_SCALE, n / 2, n / 2), n=n, fov=fov_arcmin,
        seed=hash_string(f"{ra:.4f} {dec:.4f}"),
    )
    r = new_rand(f.seed)
    lon, lat = ecliptic(ra, dec)
    f.ecl_lat = lat
    f.visits = schedule(lon, lat, now_mjd, r)

    for c in range(NUM_CHANNELS):
        row = []
        for v, vis in enumerate(f.visits):
            d = mjd_to_date(vis.mjd)
            year, week, _ = d.isocalendar()
            yday = d.timetuple().tm_yday
            row.append(Frame(
                channel=c, visit=v, mjd=vis.mjd,
                lambda_=CHANNELS[c].lambda_(vis.sub_band),
                available=float(r.random()) > 0.04,
                file=(f"level2_{year}W{week:02d}_{1 + v % 2}B_{1 + (f.seed >> (v % 40)) % 9000:04d}_1D{c + 1}"
                      f"_spx_l2b-v20-{year}-{yday:03d}.fits"),
            ))
        f.frames[c] = row

    mid = f.visits[len(f.visits) // 2].mjd if f.visits else now_mjd
    for t in TARGETS:
        s = t.source
        sra, sdec = s.position(mid)
        if separation(ra, dec, sra, sdec) < fov_arcmin / 60:
            f.target = len(f.sources)
            f.target_id = t.id
            f.name = t.name
            f.sources.append(s)
            break
    f.sources.extend(field_stars(f.wcs, r))
    return f


def schedule(lon: float, lat: float, now_mjd: float, r: np.random.Generator) -> list[Visit]:
    """Visits following the survey geometry: a position is observed when the Sun
    is about 90 degrees away in ecliptic longitude, twice a year, and near the
    ecliptic poles almost continuously."""
    s = abs(math.sin(lat * DEG))
    per_season = 17 + int(go_round(7 * s**4))
    window = 2 + 10 * s * s
    if abs(lat) > 78:
        window = 150
    end = now_mjd - PROCESSING_DAYS

    visits = []
    t = float(SURVEY_START_MJD) - 200
    season = 0
    while t < end + window:
        phase = math.fmod(sun_longitude(t) - lon - 90 + 720, 180)
        t += (180 - phase) / 0.9856474
        lo, hi = t - window / 2, t + window / 2
        if hi < SURVEY_START_MJD or lo > end:
            t += 1
            continue
        perm = r.permutation(SUB_BANDS)
        added = 0
        for j in range(per_season):
            m = lo + window * (j + 0.2 + 0.6 * float(r.random())) / per_season
            if m < SURVEY_START_MJD or m > end:
                continue
            sub = float(perm[j % SUB_BANDS]) + 0.6 * float(r.random()) - 0.3
            visits.append(Visit(mjd=m, season=season, sub_band=max(0.0, min(SUB_BANDS - 1.0, sub))))
            added += 1
        if added > 0:
            season += 1
        t += 1
    visits.sort(key=lambda v: v.mjd)
    return visits


def field_stars(w: WCS, r: np.random.Generator) -> list[Source]:
    b = abs(galactic_latitude(w.ra, w.dec))
    density = 1.2 + 6 * math.exp(-b / 12)  # stars per arcmin² to K≈17.5
    count = int(density * STAR_BOX_ARCMIN * STAR_BOX_ARCMIN)
    half = STAR_BOX_ARCMIN * 60 / w.scale / 2
    stars = []
    for _ in range(count):
        x = w.cx + (float(r.random()) * 2 - 1) * half
        y = w.cy + (float(r.random()) * 2 - 1) * half
        ra, dec = w.to_sky(x, y)
        mag = max(6.0, 17.5 + math.log10(1 - float(r.random())) / 0.32)
        u = float(r.random())
        pmra = float(r.standard_normal()) * 6
        pmdec = float(r.standard_normal()) * 6
        stars.append(Source(
            ra=ra, dec=dec, pmra=pmra, pmdec=pmdec, ref_mjd=MJD_J2000, kind=SED_STAR,
            temp=2800 + 7000 * u * u, flux=flux_from_mag(mag), ref_lambda=2.2, catalog=mag < 16,
        ))
    return stars


def load_simulated(f: Field, fr: Frame) -> None:
    """Produce the pixels of a simulated frame."""
    if fr.loaded:
        return
    try:
        if not fr.available:
            return
        n = f.n
        seed = (f.seed
                ^ (((fr.channel + 1) * 0x9E3779B97F4A7C15) & MASK64)
                ^ (((fr.visit + 1) * 0xBF58476D1CE4E5B9) & MASK64))
        r = new_rand(seed)
        ch = CHANNELS[fr.channel]

        lon, _ = ecliptic(f.wcs.ra, f.wcs.dec)
        bg = (ch.zodi * (1 + 0.15 * math.sin(2 * math.pi * fr.mjd / 365.25 + lon * DEG))
              * (1 + 0.3 * (1 - abs(math.sin(f.ecl_lat * DEG)))))
        gx = float(r.standard_normal()) * bg * 0.001
        gy = float(r.standard_normal()) * bg * 0.001
        ys, xs = np.mgrid[0:n, 0:n].astype(np.float64)
        img = bg + gx * (xs - f.wcs.cx) + gy * (ys - f.wcs.cy)

        sigma = ch.fwhm / 2.3548
        stars = []
        for s in f.sources:
            ra, dec = s.position(fr.mjd)
            x, y = f.wcs.to_pixel(ra, dec)
            if x < -6 or y < -6 or x > n + 6 or y > n + 6:
                continue
            flux = s.flux_at(fr.lambda_, fr.mjd)
            if flux > 1e-5:
                stars.append((x, y, flux))
        add_psfs(img, n, stars, sigma)

        img = img.astype(np.float32)
        flags = np.zeros((n, n), dtype=np.uint32)
        sat = img > SATURATION
        img[sat] = SATURATION
        flags[sat] |= FLAG_NONLINEAR
        img += (r.standard_normal(n * n) * ch.sigma).astype(np.float32).reshape(n, n)

        flat_img = img.reshape(-1)
        flat_flags = flags.reshape(-1)
        for _ in range(int(r.integers(n * n // 4000 + 2))):
            i = int(r.integers(n * n))
            flat_img[i] += np.float32(0.05 + 0.4 * float(r.random()))
            flat_flags[i] |= FLAG_HOT
        for _ in range(int(r.integers(n * n // 1500 + 2))):
            x, y = float(r.random()) * n, float(r.random()) * n
            a = float(r.random()) * 2 * math.pi
            e = 0.3 + 3 * float(r.random())
            for k in range(1 + int(r.integers(4))):
                px, py = int(x + k * math.cos(a)), int(y + k * math.sin(a))
                if 0 <= px < n and 0 <= py < n:
                    img[py, px] += np.float32(e)
                    flags[py, px] |= FLAG_TRANSIENT
        if float(r.random()) < 0.05:
            w = 2 + int(r.integers(4))
            x0 = n - w if int(r.integers(2)) == 1 else 0
            img[:, x0 : x0 + w] = 0
            flags[:, x0 : x0 + w] |= FLAG_MISSING

        fr.image, fr.flags = img, flags
        fr.background, fr.sigma = stats(img, flags)
    finally:
        fr.loaded = True


def add_psfs(img: np.ndarray, n: int, stars: list[tuple[float, float, float]], sigma: float) -> None:
    """Add Gaussians integrated over each pixel, so sub-pixel shifts are
    rendered faithfully."""
    if not stars:
        return
    rad = int(math.ceil(4 * sigma)) + 1
    size = min(2 * rad + 1, 32)
    k = 1 / (math.sqrt(2) * sigma)
    pos = np.array(stars, dtype=np.float64)
    x, y, flux = pos[:, 0], pos[:, 1], pos[:, 2]
    x0 = np.floor(x).astype(np.int64) - rad
    y0 = np.floor(y).astype(np.int64) - rad
    steps = np.arange(size + 1)
    ex = np.diff(_erf((x0[:, None] + steps - x[:, None]) * k), axis=1) * 0.5
    ey = np.diff(_erf((y0[:, None] + steps - y[:, None]) * k), axis=1) * 0.5
    for s in range(len(stars)):
        i0, j0 = int(x0[s]), int(y0[s])
        ia, ib = max(0, -i0), min(size, n - i0)
        ja, jb = max(0, -j0), min(size, n - j0)
        if ia >= ib or ja >= jb:
            continue
        img[j0 + ja : j0 + jb, i0 + ia : i0 + ib] += flux[s] * np.outer(ey[s, ja:jb], ex[s, ia:ib])


def _good_values(img: np.ndarray, flags: np.ndarray | None) -> np.ndarray:
    vals = img.reshape(-1).astype(np.float64)
    if flags is not None:
        vals = vals[~bad(flags.reshape(-1))]
    return vals


def stats(img: np.ndarray, flags: np.ndarray | None) -> tuple[float, float]:
    """Median and a robust sigma (scaled MAD) of unflagged pixels."""
    vals = _good_values(img, flags)
    if len(vals) == 0:
        return 0.0, 1.0
    k = len(vals) // 2
    median = float(np.partition(vals, k)[k])
    dev = np.abs(vals - median)
    mad = float(np.partition(dev, k)[k])
    return median, max(1.4826 * mad, 1e-6)


def percentile(img: np.ndarray, flags: np.ndarray | None, p: float) -> float:
    """Percentile of the unflagged pixels, p in [0, 1]."""
    vals = _good_values(img, flags)
    if len(vals) == 0:
        return 0.0
    k = min(len(vals) - 1, int(p * len(vals)))
    return float(np.partition(vals, k)[k])
