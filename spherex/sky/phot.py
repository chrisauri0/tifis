"""Aperture photometry, centroids, tracking and proper motion."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field as dc_field

import numpy as np

from .field import BAD_MASK, BAD_MASK_NO_NONLINEAR, FLAG_MISSING, NUM_CHANNELS, PIX_SCALE, Field, Frame

# Aperture and annulus radii follow the SPHEREx Source Discovery Tool.
APERTURE_RADIUS = 3.0  # pixels
ANNULUS_INNER = 7.0
ANNULUS_OUTER = 16.0
DETECTION_SNR = 5
# A tighter annulus for centroiding, where speed matters more than avoiding
# the PSF wings.
CENTROID_INNER = 4.5
CENTROID_OUTER = 7.5


def _window(fr: Frame, n: int, x: float, y: float, r: int):
    """Pixels whose indices are within r of (int(x), int(y)), clipped to the
    frame: index ranges plus pixel-center offsets from (x, y)."""
    ix, iy = int(x), int(y)
    i0, i1 = max(0, ix - r), min(n - 1, ix + r)
    j0, j1 = max(0, iy - r), min(n - 1, iy + r)
    if i0 > i1 or j0 > j1:
        return None
    ii = np.arange(i0, i1 + 1)
    jj = np.arange(j0, j1 + 1)
    dx = ii + 0.5 - x
    dy = jj + 0.5 - y
    d = np.hypot(dx[None, :], dy[:, None])
    return slice(j0, j1 + 1), slice(i0, i1 + 1), d


def local_background(fr: Frame, n: int, x: float, y: float, rin: float, rout: float) -> float:
    """3-sigma clipped median of the good annulus pixels around (x, y), as in
    the Source Discovery Tool."""
    w = _window(fr, n, x, y, int(math.ceil(rout)))
    if w is None:
        return fr.background
    sj, si, d = w
    sel = (d >= rin) & (d <= rout) & ((fr.flags[sj, si] & np.uint32(BAD_MASK)) == 0)
    vals = np.sort(fr.image[sj, si][sel].astype(np.float64))
    if len(vals) == 0:
        return fr.background
    for _ in range(5):
        med = vals[len(vals) // 2]
        std = math.sqrt(float(np.sum((vals - med) ** 2)) / len(vals))
        kept = vals[np.abs(vals - med) <= 3 * std]
        # Too few left (or nothing clipped): keep the current set.
        if len(kept) == len(vals) or len(kept) < 5:
            break
        vals = kept  # still sorted
    return float(vals[len(vals) // 2])


def aperture_full(fr: Frame, n: int, x: float, y: float) -> tuple[float, float, int, int]:
    """Background-subtracted sum inside APERTURE_RADIUS, its error, and the
    numbers of good and total aperture pixels. Pixels outside the frame or with
    bad flags (saturation aside) count as bad."""
    bg = local_background(fr, n, x, y, ANNULUS_INNER, ANNULUS_OUTER)
    r = int(math.ceil(APERTURE_RADIUS))
    ix, iy = int(x), int(y)
    ii = np.arange(ix - r, ix + r + 1)
    jj = np.arange(iy - r, iy + r + 1)
    d = np.hypot((ii + 0.5 - x)[None, :], (jj + 0.5 - y)[:, None])
    inside = d <= APERTURE_RADIUS
    npix = int(inside.sum())
    jg, ig = np.meshgrid(jj, ii, indexing="ij")
    inb = inside & (ig >= 0) & (jg >= 0) & (ig < n) & (jg < n)
    jv, iv = jg[inb], ig[inb]
    ok = (fr.flags[jv, iv] & np.uint32(BAD_MASK_NO_NONLINEAR)) == 0
    jv, iv = jv[ok], iv[ok]
    good = len(jv)
    flux = float(np.sum(fr.image[jv, iv].astype(np.float64) - bg))
    if fr.variance is not None:
        var = float(np.sum(fr.variance[jv, iv].astype(np.float64)))
        err = math.sqrt(var) if var >= 0 else math.nan
    else:
        nann = math.pi * (ANNULUS_OUTER**2 - ANNULUS_INNER**2)
        err = fr.sigma * math.sqrt(npix + math.pi / 2 * npix * npix / nann)
    return flux, err, good, npix


def aperture(fr: Frame, n: int, x: float, y: float) -> tuple[float, float, bool]:
    """Flux, error and whether the measurement is reliable (fewer than 30 % of
    the aperture pixels bad)."""
    flux, err, good, npix = aperture_full(fr, n, x, y)
    return flux, err, npix > 0 and (npix - good) < 0.3 * npix


def centroid(fr: Frame, n: int, x: float, y: float, max_shift: float) -> tuple[float, float, float]:
    """Refine a position with a flux-weighted mean, moving at most max_shift
    pixels. snr reports how clearly there is a source there."""
    bg = local_background(fr, n, x, y, CENTROID_INNER, CENTROID_OUTER)
    cx, cy, snr = x, y, 0.0
    img, flags = fr.image, fr.flags
    for _ in range(4):
        sw = sx = sy = total = 0.0
        npix = 0
        icx, icy = int(cx), int(cy)
        for j in range(icy - 2, icy + 3):
            if j < 0 or j >= n:
                continue
            py = j + 0.5
            for i in range(icx - 2, icx + 3):
                # Bright stars saturate and get their cores flagged, yet those
                # pixels still mark where the star is; only missing data is skipped.
                if i < 0 or i >= n or int(flags[j, i]) & FLAG_MISSING:
                    continue
                px = i + 0.5
                if math.hypot(px - cx, py - cy) > 2:
                    continue
                v = float(img[j, i]) - bg
                total += v
                npix += 1
                if v > 0:
                    sw += v
                    sx += v * px
                    sy += v * py
        if npix == 0 or sw == 0:
            return x, y, 0.0
        snr = total / (fr.sigma * math.sqrt(npix))
        nx, ny = sx / sw, sy / sw
        dist = math.hypot(nx - x, ny - y)
        if dist > max_shift:
            nx, ny = x + (nx - x) * max_shift / dist, y + (ny - y) * max_shift / dist
        cx, cy = nx, ny
    return cx, cy, snr


@dataclass
class TrackPoint:
    visit: int
    x: float
    y: float

    def to_json(self) -> dict:
        return {"v": self.visit, "x": self.x, "y": self.y}


@dataclass
class Motion:
    """Linear fit of position against time, in pixels and days."""

    x0: float = 0.0
    y0: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    t0: float = 0.0
    err_vx: float = 0.0  # standard errors of the velocity, px/day
    err_vy: float = 0.0
    points: list[TrackPoint] = dc_field(default_factory=list)
    moving: bool = False

    def at(self, mjd: float) -> tuple[float, float]:
        return self.x0 + self.vx * (mjd - self.t0), self.y0 + self.vy * (mjd - self.t0)

    def proper_motion(self) -> tuple[float, float]:
        """arcsec/yr, east and north positive."""
        return -self.vx * PIX_SCALE * 365.25, -self.vy * PIX_SCALE * 365.25

    def proper_motion_err(self) -> tuple[float, float]:
        return self.err_vx * PIX_SCALE * 365.25, self.err_vy * PIX_SCALE * 365.25

    def fit(self, f: Field, pts: list[TrackPoint]) -> None:
        ts = [f.visits[p.visit].mjd for p in pts]
        k = float(len(pts))
        self.t0 = sum(ts) / k
        self.x0 = sum(p.x for p in pts) / k
        self.y0 = sum(p.y for p in pts) / k
        self.vx = self.vy = 0.0
        self.moving = False
        if max(ts) - min(ts) < 60:
            return
        stt = stx = sty = 0.0
        for p, t in zip(pts, ts):
            dt = t - self.t0
            stt += dt * dt
            stx += dt * (p.x - self.x0)
            sty += dt * (p.y - self.y0)
        self.vx, self.vy = stx / stt, sty / stt
        # Slope errors from the scatter around the fit.
        if len(pts) > 2:
            rx = ry = 0.0
            for p, t in zip(pts, ts):
                x, y = self.at(t)
                rx += (p.x - x) ** 2
                ry += (p.y - y) ** 2
            self.err_vx = math.sqrt(rx / (len(pts) - 2)) / math.sqrt(stt)
            self.err_vy = math.sqrt(ry / (len(pts) - 2)) / math.sqrt(stt)
        # A motion counts when it is significant and above ~0.2 px/yr, below
        # which it is indistinguishable from noise at this pixel size.
        speed = math.hypot(self.vx, self.vy)
        self.moving = speed * 365.25 > 0.2 and speed > 3 * math.hypot(self.err_vx, self.err_vy)
        if not self.moving:
            self.vx = self.vy = 0.0


def track(f: Field, ch: int, visit: int, x: float, y: float) -> Motion:
    """Follow the centroid of a source through every loaded frame of a channel,
    starting at the visit where it was picked, and fit its motion."""
    order = [v for v, fr in enumerate(f.frames[ch]) if fr.loaded and fr.available]
    start = bisect.bisect_left(order, visit)
    pts: list[TrackPoint] = []

    def follow(idx):
        gx, gy = x, y
        for v in idx:
            cx, cy, snr = centroid(f.frames[ch][v], f.n, gx, gy, 1.5)
            if snr >= DETECTION_SNR:
                gx, gy = cx, cy
                pts.append(TrackPoint(v, cx, cy))

    follow(order[start:])
    follow(reversed(order[:start]))
    pts.sort(key=lambda p: p.visit)

    m = Motion(x0=x, y0=y, points=pts)
    if not pts:
        return m
    m.fit(f, pts)
    # One pass of outlier rejection.
    kept = []
    for p in pts:
        px, py = m.at(f.visits[p.visit].mjd)
        if math.hypot(p.x - px, p.y - py) < 0.6:
            kept.append(p)
    if 2 <= len(kept) < len(pts):
        m.fit(f, kept)
    return m


@dataclass
class Measurement:
    channel: int
    visit: int
    mjd: float
    lambda_: float
    flux: float
    err: float
    ok: bool

    def to_json(self) -> dict:
        return {"c": self.channel, "v": self.visit, "t": self.mjd, "l": self.lambda_,
                "f": self.flux, "e": self.err, "ok": self.ok}


def measure(f: Field, m: Motion) -> list[Measurement]:
    """Forced photometry along the fitted motion in every loaded frame of every
    channel: that gives the spectrum and the light curves at once."""
    out = []
    for c in range(NUM_CHANNELS):
        for fr in f.frames[c]:
            if not fr.loaded or not fr.available:
                continue
            x, y = m.at(fr.mjd)
            flux, err, good, npix = aperture_full(fr, f.n, x, y)
            if good == 0:
                # Nothing usable in the aperture, e.g. a fully saturated core.
                continue
            ok = (npix - good) < 0.3 * npix
            lam = fr.lambda_at(*f.wcs.to_sky(x, y))
            out.append(Measurement(c, fr.visit, fr.mjd, lam, flux * f.flux_scale, err * f.flux_scale, ok))
    return out
