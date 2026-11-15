"""The two coordinate systems of a SPHEREx spectral image: the celestial TAN-SIP
projection and the WAVE-TAB lookup table that gives the wavelength seen by each
pixel.

Pixel coordinates are 0-based, with (0, 0) at the center of the first pixel of
the first FITS row, as in astropy. Every function accepts scalars or numpy
arrays.
"""

from __future__ import annotations

import numpy as np

from . import fits

DEG = np.pi / 180


class WCSError(ValueError):
    pass


class Poly:
    """SIP polynomial: sum of c * u**i * v**j."""

    def __init__(self, coeffs: dict[tuple[int, int], float] | None = None):
        self.c = coeffs or {}

    @classmethod
    def read(cls, h: fits.HDU, name: str) -> "Poly":
        order = h.int(name + "_ORDER", 0)
        c = {}
        for i in range(order + 1):
            for j in range(order + 1 - i):
                v = h.float(f"{name}_{i}_{j}", 0)
                if v != 0:
                    c[(i, j)] = v
        return cls(c)

    def __call__(self, u, v):
        s = 0.0
        for (i, j), c in self.c.items():
            s = s + c * u**i * v**j
        return s


class Celestial:
    """TAN projection with optional SIP distortion."""

    def __init__(self, h: fits.HDU):
        ctype = h.keyword("CTYPE1")
        if ctype not in ("RA---TAN", "RA---TAN-SIP"):
            raise WCSError(f"wcs: unsupported projection {ctype!r}")
        self.crpix = (h.float("CRPIX1", 0), h.float("CRPIX2", 0))
        self.crval = (h.float("CRVAL1", 0), h.float("CRVAL2", 0))
        if h.keyword("CD1_1") != "":
            cd = ((h.float("CD1_1", 0), h.float("CD1_2", 0)), (h.float("CD2_1", 0), h.float("CD2_2", 0)))
        else:
            d1, d2 = h.float("CDELT1", 1), h.float("CDELT2", 1)
            cd = (
                (d1 * h.float("PC1_1", 1), d1 * h.float("PC1_2", 0)),
                (d2 * h.float("PC2_1", 0), d2 * h.float("PC2_2", 1)),
            )
        det = cd[0][0] * cd[1][1] - cd[0][1] * cd[1][0]
        if det == 0:
            raise WCSError("wcs: singular CD matrix")
        self.cd = cd
        self.inv = ((cd[1][1] / det, -cd[0][1] / det), (-cd[1][0] / det, cd[0][0] / det))
        if ctype == "RA---TAN-SIP":
            self.a, self.b = Poly.read(h, "A"), Poly.read(h, "B")
            self.ap, self.bp = Poly.read(h, "AP"), Poly.read(h, "BP")
        else:
            self.a = self.b = self.ap = self.bp = Poly()

    def pixel_to_sky(self, x, y):
        """0-based pixel coordinates to RA and Dec in degrees."""
        cd = self.cd
        u = np.asarray(x, dtype=np.float64) + 1 - self.crpix[0]
        v = np.asarray(y, dtype=np.float64) + 1 - self.crpix[1]
        u, v = u + self.a(u, v), v + self.b(u, v)
        xi = (cd[0][0] * u + cd[0][1] * v) * DEG
        eta = (cd[1][0] * u + cd[1][1] * v) * DEG
        a0, d0 = self.crval[0] * DEG, self.crval[1] * DEG
        den = np.cos(d0) - eta * np.sin(d0)
        ra = a0 + np.arctan2(xi, den)
        dec = np.arctan2(np.sin(d0) + eta * np.cos(d0), np.hypot(xi, den))
        return _out(np.fmod(ra / DEG + 360, 360)), _out(dec / DEG)

    def sky_to_pixel(self, ra, dec):
        """RA and Dec in degrees to 0-based pixel coordinates.
        Returns (x, y, ok); ok is False on the far side of the projection,
        where x and y are 0."""
        a = np.asarray(ra, dtype=np.float64) * DEG
        d = np.asarray(dec, dtype=np.float64) * DEG
        a0, d0 = self.crval[0] * DEG, self.crval[1] * DEG
        cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
        ok = cosc > 0
        safe = np.where(ok, cosc, 1.0)
        xi = np.cos(d) * np.sin(a - a0) / safe / DEG
        eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / safe / DEG
        inv = self.inv
        up = inv[0][0] * xi + inv[0][1] * eta
        vp = inv[1][0] * xi + inv[1][1] * eta
        # Start from the inverse polynomial and polish it against the forward
        # one, since AP/BP only approximate the inverse of A/B.
        u, v = up + self.ap(up, vp), vp + self.bp(up, vp)
        for _ in range(3):
            fu, fv = u + self.a(u, v), v + self.b(u, v)
            u, v = u - (fu - up), v - (fv - vp)
        x = np.where(ok, u + self.crpix[0] - 1, 0.0)
        y = np.where(ok, v + self.crpix[1] - 1, 0.0)
        return _out(x), _out(y), _out(ok)


class Wave:
    """WAVE-TAB spectral WCS: a grid of control points on the parent detector
    with the central wavelength and bandwidth at each one, interpolated
    bilinearly. Distortion does not apply to it."""

    def __init__(self, image: fits.HDU, hdus: list[fits.HDU]):
        if image.keyword("CTYPE1W") != "WAVE-TAB":
            raise WCSError("wcs: no WAVE-TAB spectral WCS")
        table = fits.find(hdus, image.keyword("PS1_0W"))
        if table is None:
            raise WCSError(f"wcs: missing {image.keyword('PS1_0W')} extension")
        self.crpix = (image.float("CRPIX1W", 0), image.float("CRPIX2W", 0))
        self.crval = (image.float("CRVAL1W", 0), image.float("CRVAL2W", 0))
        self.cdelt = (image.float("CDELT1W", 1), image.float("CDELT2W", 1))
        self.x = table.column(image.keyword("PS1_2W"))
        self.y = table.column(image.keyword("PS2_2W"))
        self.values = table.column(image.keyword("PS1_1W"))
        if len(self.values) != 2 * len(self.x) * len(self.y) or len(self.x) < 2 or len(self.y) < 2:
            raise WCSError("wcs: WAVE-TAB sizes do not match")

    def at(self, x, y):
        """Central wavelength and bandwidth in µm seen by a 0-based pixel."""
        px = (np.asarray(x, dtype=np.float64) + 1 - self.crpix[0]) * self.cdelt[0] + self.crval[0]
        py = (np.asarray(y, dtype=np.float64) + 1 - self.crpix[1]) * self.cdelt[1] + self.crval[1]
        i, fx = _cell(self.x, px)
        j, fy = _cell(self.y, py)
        nx = len(self.x)

        def val(ii, jj, k):
            return self.values[2 * (ii + nx * jj) + k]

        out = []
        for k in range(2):
            out.append(
                (1 - fx) * (1 - fy) * val(i, j, k)
                + fx * (1 - fy) * val(i + 1, j, k)
                + (1 - fx) * fy * val(i, j + 1, k)
                + fx * fy * val(i + 1, j + 1, k)
            )
        return _out(out[0]), _out(out[1])


def _cell(ctrl: np.ndarray, p):
    """Interval of p in the increasing control points and the fractional
    position inside it, clamped to the table."""
    i = np.searchsorted(ctrl, p, side="left") - 1
    i = np.clip(i, 0, len(ctrl) - 2)
    f = (p - ctrl[i]) / (ctrl[i + 1] - ctrl[i])
    return i, np.clip(f, 0.0, 1.0)


def _out(a):
    """Plain Python scalars for 0-d results, arrays otherwise."""
    a = np.asarray(a)
    return a.item() if a.ndim == 0 else a
