"""Point sources with linear proper motion, a spectral shape and a light curve."""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass

from .grid import DEG
from .rand import new_rand

SED_STAR, SED_BROWN_DWARF, SED_Y_DWARF, SED_MIRA, SED_YOUNG = range(5)

# Epoch of Gaia DR3 positions, J2016.0.
GAIA_EPOCH = 57388.5


@dataclass
class Source:
    name: str = ""
    ra: float = 0.0  # degrees at ref_mjd
    dec: float = 0.0
    pmra: float = 0.0  # mas/yr, includes cos(dec)
    pmdec: float = 0.0
    ref_mjd: float = 0.0
    kind: int = SED_STAR
    temp: float = 0.0  # K
    flux: float = 0.0  # F_nu at ref_lambda, image units summed over the PSF
    ref_lambda: float = 0.0  # µm
    period: float = 0.0  # days
    amp: float = 0.0  # mag at 1.2 µm
    phase: float = 0.0  # MJD of maximum
    catalog: bool = False  # listed in the Gaia/WISE layer
    catalog_name: str = ""  # which catalog the position comes from
    catalog_mjd: float = 0.0  # epoch of the catalog position; 0 means Gaia DR3
    catalog_mag: float = 0.0  # Gaia G or WISE W1/W2; 0 when unknown
    seed: int = 0

    def catalog_epoch(self) -> float:
        return GAIA_EPOCH if self.catalog_mjd == 0 else self.catalog_mjd

    def position(self, mjd: float) -> tuple[float, float]:
        yr = (mjd - self.ref_mjd) / 365.25
        dec = self.dec + self.pmdec * yr / 3.6e6
        ra = self.ra + self.pmra * yr / 3.6e6 / math.cos(self.dec * DEG)
        return ra, dec

    def flux_at(self, lam: float, mjd: float) -> float:
        ref = self.shape(self.ref_lambda)
        if ref <= 0:
            return 0.0
        return self.flux * self.shape(lam) / ref * 10 ** (-0.4 * self.dmag(lam, mjd))

    def shape(self, lam: float) -> float:
        if self.kind in (SED_BROWN_DWARF, SED_Y_DWARF):
            return _absorb(planck_nu(lam, self.temp), lam, BROWN_DWARF_BANDS)
        if self.kind == SED_MIRA:
            return _absorb(planck_nu(lam, self.temp), lam, MIRA_BANDS)
        if self.kind == SED_YOUNG:
            star = planck_nu(lam, self.temp) / planck_nu(2.2, self.temp)
            disk = 1.2 * planck_nu(lam, 1100) / planck_nu(2.2, 1100)
            return _absorb(star + disk, lam, YOUNG_BANDS)
        return planck_nu(lam, self.temp)

    def dmag(self, lam: float, mjd: float) -> float:
        """Magnitude offset at a given time; positive means fainter."""
        if self.kind == SED_MIRA:
            amp = self.amp * (1.2 / lam) ** 0.6
            return -amp * math.cos(2 * math.pi * (mjd - self.phase) / self.period)
        if self.kind == SED_YOUNG:
            amp = self.amp * (1.2 / lam) ** 0.8
            return amp * irregular(mjd, self.seed)
        return 0.0


# (center, width, depth) of absorption bands, µm.
BROWN_DWARF_BANDS = (
    (1.15, 0.05, 0.5), (1.4, 0.08, 0.75), (1.65, 0.04, 0.45), (1.9, 0.10, 0.75),
    (2.25, 0.12, 0.5), (2.7, 0.20, 0.8), (3.3, 0.15, 0.85), (4.6, 0.12, 0.35),
)
MIRA_BANDS = ((1.4, 0.08, 0.4), (1.9, 0.10, 0.4), (2.3, 0.05, 0.3), (2.7, 0.20, 0.5), (4.6, 0.10, 0.35))
YOUNG_BANDS = ((3.05, 0.15, 0.25), (4.67, 0.06, 0.2))


def planck_nu(lam: float, temp: float) -> float:
    """B_nu up to a constant, lam in µm."""
    x = 14387.77 / (lam * temp)
    if x > 700:
        return 0.0
    return 1 / (lam * lam * lam * math.expm1(x))


def _absorb(f: float, lam: float, bands) -> float:
    for center, width, depth in bands:
        d = (lam - center) / width
        f *= 1 - depth * math.exp(-0.5 * d * d)
    return f


@functools.lru_cache(maxsize=64)
def _irregular_phases(seed: int) -> tuple[float, ...]:
    r = new_rand(seed)
    return tuple(float(r.random()) * 2 * math.pi for _ in range(5))


def irregular(mjd: float, seed: int) -> float:
    """A smooth, deterministic wobble in [-1, 1.5] with occasional dips, shaped
    like the dimming episodes of young stars."""
    ph = _irregular_phases(seed)
    v = 0.0
    for k, p in enumerate((3.1, 11.7, 37.0, 142.0)):
        v += 0.25 * math.sin(2 * math.pi * mjd / p + ph[k])
    dip = math.sin(2 * math.pi * mjd / 410 + ph[4])
    if dip > 0.6:
        v += 2.5 * (dip - 0.6)
    return max(-1.0, min(1.5, v))


def flux_from_mag(mag: float) -> float:
    return 10 * 10 ** (-0.4 * (mag - 10))
