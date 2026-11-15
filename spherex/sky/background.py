"""Background plane removal for epoch differences."""

from __future__ import annotations

import numpy as np

from .field import bad, stats


def subtract_plane(img: np.ndarray, flags: np.ndarray | None, n: int, sigma: float) -> None:
    """Remove, in place, a tilted background a + b·x + c·y fitted to the
    unflagged pixels, ignoring sources with two passes of sigma clipping.
    Zodiacal light changes between visits, so differences need this."""
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float64)
    vals = img.astype(np.float64)
    good = np.ones((n, n), dtype=bool) if flags is None else ~bad(flags)
    median, _ = stats(img, flags)
    a, b, c = median, 0.0, 0.0
    for _ in range(2):
        keep = good & (np.abs(vals - (a + b * xs + c * ys)) < 3 * sigma)
        x, y, v = xs[keep], ys[keep], vals[keep]
        # Normal equations for least squares in (1, x, y).
        s = np.array([
            [keep.sum(), x.sum(), y.sum()],
            [x.sum(), (x * x).sum(), (x * y).sum()],
            [y.sum(), (y * x).sum(), (y * y).sum()],
        ], dtype=np.float64)
        r = np.array([v.sum(), (x * v).sum(), (y * v).sum()], dtype=np.float64)
        sol = solve3(s, r)
        if sol is None:
            break
        a, b, c = sol
    img -= (a + b * xs + c * ys).astype(np.float32)


def _det3(m) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def solve3(m: np.ndarray, r: np.ndarray) -> tuple[float, float, float] | None:
    """Cramer's rule; None for a (nearly) singular system."""
    m = [[float(v) for v in row] for row in m]
    d = _det3(m)
    if abs(d) < 1e-12:
        return None
    out = []
    for col in range(3):
        mc = [row[:] for row in m]
        for row in range(3):
            mc[row][col] = float(r[row])
        out.append(_det3(mc) / d)
    return out[0], out[1], out[2]
