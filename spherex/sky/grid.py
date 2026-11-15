"""The field grid (gnomonic, north up, east left) and sky/time helpers."""

from __future__ import annotations

import datetime as dt
import math
import time

import numpy as np

DEG = math.pi / 180
ARCSEC = DEG / 3600

MJD_UNIX = 40587.0
MJD_J2000 = 51544.5

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
_NS_PER_DAY = 86400 * 10**9


class WCS:
    """Gnomonic projection with north up, east left and square pixels.
    Pixel i covers [i, i+1), so the center of the first pixel is at 0.5."""

    __slots__ = ("ra", "dec", "scale", "cx", "cy")

    def __init__(self, ra: float, dec: float, scale: float, cx: float, cy: float):
        self.ra, self.dec, self.scale, self.cx, self.cy = ra, dec, scale, cx, cy

    def to_pixel(self, ra: float, dec: float) -> tuple[float, float]:
        a, d = ra * DEG, dec * DEG
        a0, d0 = self.ra * DEG, self.dec * DEG
        cosc = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
        xi = math.cos(d) * math.sin(a - a0) / cosc
        eta = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(a - a0)) / cosc
        s = self.scale * ARCSEC
        return self.cx - xi / s, self.cy - eta / s

    def to_sky(self, x: float, y: float) -> tuple[float, float]:
        s = self.scale * ARCSEC
        xi = -(x - self.cx) * s
        eta = -(y - self.cy) * s
        rho = math.hypot(xi, eta)
        if rho == 0:
            return self.ra, self.dec
        a0, d0 = self.ra * DEG, self.dec * DEG
        c = math.atan(rho)
        sinc, cosc = math.sin(c), math.cos(c)
        d = math.asin(max(-1.0, min(1.0, cosc * math.sin(d0) + eta * sinc * math.cos(d0) / rho)))
        a = a0 + math.atan2(xi * sinc, rho * math.cos(d0) * cosc - eta * math.sin(d0) * sinc)
        return math.fmod(a / DEG + 360, 360), d / DEG

    def to_sky_array(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """to_sky for arrays of pixel coordinates."""
        s = self.scale * ARCSEC
        xi = -(np.asarray(x, dtype=np.float64) - self.cx) * s
        eta = -(np.asarray(y, dtype=np.float64) - self.cy) * s
        rho = np.hypot(xi, eta)
        zero = rho == 0
        r = np.where(zero, 1.0, rho)
        a0, d0 = self.ra * DEG, self.dec * DEG
        c = np.arctan(r)
        sinc, cosc = np.sin(c), np.cos(c)
        d = np.arcsin(np.clip(cosc * np.sin(d0) + eta * sinc * np.cos(d0) / r, -1, 1))
        a = a0 + np.arctan2(xi * sinc, r * np.cos(d0) * cosc - eta * np.sin(d0) * sinc)
        ra = np.where(zero, self.ra, np.fmod(a / DEG + 360, 360))
        dec = np.where(zero, self.dec, d / DEG)
        return ra, dec


def separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular distance between two positions, in degrees."""
    a = math.sin((dec2 - dec1) * DEG / 2)
    b = math.sin((ra2 - ra1) * DEG / 2)
    h = a * a + math.cos(dec1 * DEG) * math.cos(dec2 * DEG) * b * b
    return 2 * math.asin(math.sqrt(min(1.0, h))) / DEG


def mjd_to_datetime(mjd: float) -> dt.datetime:
    """UTC time of an MJD, to the nanosecond truncated toward zero like Go's
    time.Duration conversion (Python datetimes keep microseconds)."""
    ns = int((mjd - MJD_UNIX) * 86400e9)
    return _EPOCH + dt.timedelta(microseconds=ns // 1000)


def mjd_to_date(mjd: float) -> dt.date:
    ns = int((mjd - MJD_UNIX) * 86400e9)
    return (_EPOCH + dt.timedelta(days=ns // _NS_PER_DAY)).date()


def mjd_to_iso_date(mjd: float) -> str:
    return mjd_to_date(mjd).isoformat()


def time_to_mjd(t: float | None = None) -> float:
    """MJD of a Unix time in seconds (now by default)."""
    if t is None:
        return MJD_UNIX + time.time_ns() / 86400e9
    return MJD_UNIX + t / 86400


def now_mjd() -> float:
    return time_to_mjd()


def ecliptic(ra: float, dec: float) -> tuple[float, float]:
    """Equatorial (J2000) to ecliptic longitude and latitude, degrees."""
    eps = 23.4393 * DEG
    a, d = ra * DEG, dec * DEG
    b = math.asin(max(-1.0, min(1.0, math.sin(d) * math.cos(eps) - math.cos(d) * math.sin(eps) * math.sin(a))))
    lon = math.atan2(math.sin(a) * math.cos(eps) + math.tan(d) * math.sin(eps), math.cos(a))
    return math.fmod(lon / DEG + 360, 360), b / DEG


def galactic_latitude(ra: float, dec: float) -> float:
    """Enough to scale star density with the Milky Way."""
    ra_ngp, dec_ngp = 192.85948 * DEG, 27.12825 * DEG
    a, d = ra * DEG, dec * DEG
    s = math.sin(d) * math.sin(dec_ngp) + math.cos(d) * math.cos(dec_ngp) * math.cos(a - ra_ngp)
    return math.asin(max(-1.0, min(1.0, s))) / DEG


def sun_longitude(mjd: float) -> float:
    """Mean ecliptic longitude of the Sun, good to about 2 degrees."""
    return math.fmod(280.460 + 0.9856474 * (mjd - MJD_J2000), 360)
