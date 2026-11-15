"""Nested HEALPix pixels, as encoded in Gaia source_id values.

Gaia source_id values carry the HEALPix index (nested scheme, order 12) of the
source in their top bits: source_id / 2**35. Bulk files are ordered by
source_id, so by sky pixel.
"""

from __future__ import annotations

import math

# Order of the pixels used as cache tiles: about 0.23 degrees across.
ORDER = 8


def pixel_of(source_id: int) -> int:
    """The order-8 pixel encoded in a source_id."""
    return source_id >> (35 + 2 * (12 - ORDER))


def ang2pix(order: int, ra: float, dec: float) -> int:
    """Nested HEALPix pixel containing (ra, dec) in degrees."""
    nside = 1 << order
    z = math.sin(dec * math.pi / 180)
    za = abs(z)
    tt = math.fmod(ra / 90, 4)  # phi in units of pi/2
    if tt < 0:
        tt += 4
    if za <= 2.0 / 3:
        # Equatorial region: faces 0-11 along the two families of edge lines.
        t1 = nside * (0.5 + tt)
        t2 = nside * z * 0.75
        jp = int(t1 - t2)
        jm = int(t1 + t2)
        ifp, ifm = jp // nside, jm // nside
        if ifp == ifm:
            face = ifp | 4
        elif ifp < ifm:
            face = ifp
        else:
            face = ifm + 8
        ix = jm & (nside - 1)
        iy = nside - (jp & (nside - 1)) - 1
    else:
        # Polar caps.
        ntt = min(int(tt), 3)
        tp = tt - ntt
        tmp = nside * math.sqrt(3 * (1 - za))
        jp = min(int(tp * tmp), nside - 1)
        jm = min(int((1 - tp) * tmp), nside - 1)
        if z >= 0:
            face, ix, iy = ntt, nside - jm - 1, nside - jp - 1
        else:
            face, ix, iy = ntt + 8, jp, jm
    return (face << (2 * order)) + _spread(ix) + (_spread(iy) << 1)


def _spread(v: int) -> int:
    """Interleave the bits of v with zeros: abc -> 0a0b0c."""
    out = 0
    i = 0
    while v:
        out |= (v & 1) << (2 * i)
        v >>= 1
        i += 1
    return out


def disc_pixels(ra: float, dec: float, radius: float) -> list[int]:
    """Order-8 pixels touching a circle of radius degrees, by sampling it more
    finely than the pixel size."""
    step = 0.05  # degrees, a quarter of a pixel
    seen = {ang2pix(ORDER, ra, dec): None}
    cos_dec = max(math.cos(dec * math.pi / 180), 1e-6)
    n = int(math.ceil(radius / step))
    for j in range(-n, n + 1):
        for i in range(-n, n + 1):
            dy, dx = j * step, i * step
            if math.hypot(dx, dy) > radius + step:
                continue
            d = max(-90.0, min(90.0, dec + dy))
            seen.setdefault(ang2pix(ORDER, ra + dx / cos_dec, d), None)
    return list(seen)
