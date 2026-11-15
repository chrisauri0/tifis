"""Turning frames into the image on screen: epoch, difference and sum, the
display stretch, and the overlay geometry the browser draws on top."""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass

import numpy as np

from .. import sky

# Okabe-Ito colors, ordered from short to long wavelength; the UI uses the same.
CHANNEL_COLORS = (
    (0, 114, 178), (86, 180, 233), (0, 158, 115), (240, 228, 66), (230, 159, 0), (213, 94, 0),
)


@dataclass
class Stretch:
    ready: bool = False
    median: float = 0.0
    sigma: float = 0.0
    high: float = 0.0


@dataclass
class ViewState:
    band: int = 2
    mode: str = "epoch"  # epoch, diff or sum
    visit: int = 0
    ref: int = -1  # -1 picks the reference automatically
    flags: bool = False
    catalog: bool = False
    tint: bool = False

    @classmethod
    def from_json(cls, d: dict) -> "ViewState":
        """Missing fields take zero values, as the UI always sends them all."""
        if not isinstance(d, dict):
            raise ValueError("view must be an object")
        return cls(band=_int(d.get("band", 0)), mode=_str(d.get("mode", "")), visit=_int(d.get("visit", 0)),
                   ref=_int(d.get("ref", 0)), flags=_bool(d.get("flags", False)),
                   catalog=_bool(d.get("catalog", False)), tint=_bool(d.get("tint", False)))


def _int(v) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
        raise ValueError(f"not an integer: {v!r}")
    return int(v)


def _str(v) -> str:
    if not isinstance(v, str):
        raise ValueError(f"not a string: {v!r}")
    return v


def _bool(v) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"not a boolean: {v!r}")
    return v


def reference(f: sky.Field, v: ViewState) -> int:
    """Epoch A for the difference. Automatic mode looks in another season for a
    visit at nearly the same wavelength, as far away in time as possible: same
    color, longest baseline."""
    frames = f.frames[v.band]
    if 0 <= v.ref < len(frames) and v.ref != v.visit:
        return v.ref
    cur = f.visits[v.visit]
    best, best_score = -1, math.inf
    for i, fr in enumerate(frames):
        if i == v.visit or not fr.loaded or not fr.available:
            continue
        vis = f.visits[i]
        dsub = abs(vis.sub_band - cur.sub_band)
        score = 0.0 if dsub <= 1 else dsub * 1000
        if vis.season == cur.season:
            score += 1e6
        score -= abs(vis.mjd - cur.mjd)
        if score < best_score:
            best, best_score = i, score
    return best


def compose(f: sky.Field, v: ViewState, st: Stretch):
    """The values and flags to show for the current view (None when there is
    nothing to show), and the frame info for the UI."""
    n = f.n
    fr = f.frames[v.band][v.visit]
    info = {
        "band": v.band, "mode": v.mode, "visit": v.visit, "ref": -1,
        "loaded": fr.loaded, "available": fr.available,
        "mjd": fr.mjd, "date": sky.mjd_to_iso_date(fr.mjd), "lambda": fr.lambda_, "file": fr.file,
        "bg": fr.background, "sigma": fr.sigma, "flagged": 0,
    }
    vals = flags = None
    if v.mode == "diff":
        ref = reference(f, v)
        info["ref"] = ref
        if ref >= 0:
            ref_lambda = f.frames[v.band][ref].lambda_
            if ref_lambda != 0:
                info["refLambda"] = ref_lambda
        a = f.frames[v.band][ref] if ref >= 0 else None
        # A manually fixed reference may be missing in this channel.
        if a is not None and fr.loaded and fr.available and a.loaded and a.available:
            vals = fr.image - a.image
            flags = fr.flags | a.flags
            sky.subtract_plane(vals, flags, n, st.sigma * math.sqrt(2))
    elif v.mode == "sum":
        lo = v.ref if 0 <= v.ref <= v.visit else 0
        info["ref"] = lo
        total = np.zeros((n, n), dtype=np.float64)
        count = np.zeros((n, n), dtype=np.int64)
        stacked = 0
        for i in range(lo, v.visit + 1):
            s = f.frames[v.band][i]
            if not s.loaded or not s.available:
                continue
            stacked += 1
            off = st.median - s.background
            good = ~sky.bad(s.flags, sky.field.BAD_MASK_NO_NONLINEAR)
            total += np.where(good, s.image.astype(np.float64) + off, 0.0)
            count += good
        if stacked > 0:
            info["stacked"] = stacked
            have = count > 0
            vals = np.where(have, total / np.where(have, count, 1), st.median).astype(np.float32)
            flags = np.where(have, 0, sky.FLAG_MISSING).astype(np.uint32)
        info["loaded"] = stacked > 0
    elif fr.loaded and fr.available:
        vals, flags = fr.image, fr.flags

    if flags is not None:
        info["flagged"] = int(sky.bad(flags).sum())
    return vals, flags, info


def colorize(vals: np.ndarray, v: ViewState, st: Stretch) -> np.ndarray:
    """RGBA bytes, shape (n, n, 4), for values with the channel's stretch."""
    x = vals.astype(np.float64)
    with np.errstate(all="ignore"):
        if v.mode == "diff":
            t = 0.5 + 0.5 * np.arcsinh(x / st.sigma / 2) / math.asinh(20)
            g = _byte(255 * _clamp01(t))
            rgb = np.stack([g, g, g], axis=-1)
        else:
            lo = math.asinh(-0.75)
            hi = math.asinh(st.high / st.sigma / 2) if st.sigma else math.inf
            t = _clamp01((np.arcsinh((x - st.median) / st.sigma / 2) - lo) / (hi - lo))
            if not v.tint:
                g = _byte(255 * t)
                rgb = np.stack([g, g, g], axis=-1)
            else:
                w = t**4
                rgb = np.stack([_byte(c * t + (255 - c) * w) for c in CHANNEL_COLORS[v.band]], axis=-1)
    out = np.empty(vals.shape + (4,), dtype=np.uint8)
    out[..., :3] = rgb
    out[..., 3] = 255
    return out


def _clamp01(t: np.ndarray) -> np.ndarray:
    return np.clip(np.nan_to_num(t, nan=0.0), 0.0, 1.0)


def _byte(x: np.ndarray) -> np.ndarray:
    """uint8 conversion truncating toward zero."""
    return np.clip(np.nan_to_num(x, nan=0.0), 0, 255).astype(np.uint8)


def image_event(f: sky.Field, vals: np.ndarray | None, flags: np.ndarray | None, v: ViewState, st: Stretch) -> dict:
    """Payload of the 'image' event: RGBA pixels and, when the flag layer is on,
    a byte per pixel marking bad ones."""
    if vals is None:
        return {"n": f.n, "rgba": None, "flags": None}
    rgba = colorize(vals, v, st)
    out = {"n": f.n, "rgba": base64.b64encode(rgba.tobytes()).decode("ascii"), "flags": None}
    if v.flags and flags is not None:
        out["flags"] = base64.b64encode(sky.bad(flags).astype(np.uint8).tobytes()).decode("ascii")
    return out


def overlay(f: sky.Field, v: ViewState, sel) -> dict:
    """Geometry drawn over the image, in image pixels: the field center, the
    catalog layer and the selected source."""
    mjd = f.visits[v.visit].mjd if f.visits else 0.0
    out = {"center": [f.wcs.cx, f.wcs.cy], "catalog": [], "selection": None}
    if v.catalog:
        for i, s in enumerate(f.sources):
            # Faint catalog stars that SPHEREx cannot see would only clutter the
            # view; fast movers are always worth an arrow.
            fast = math.hypot(s.pmra, s.pmdec) > 100
            if not s.catalog or (s.catalog_mag > 16 and not fast and i != f.target):
                continue
            x0, y0 = f.wcs.to_pixel(*s.position(s.catalog_epoch()))
            x1, y1 = f.wcs.to_pixel(*s.position(mjd))
            if x1 < 0 or y1 < 0 or x1 > f.n or y1 > f.n:
                continue
            out["catalog"].append({
                "x0": x0, "y0": y0, "x1": x1, "y1": y1, "target": i == f.target, "name": s.name,
                "arrow": math.hypot(x1 - x0, y1 - y0) > 0.25,
            })
    if sel is not None and sel.motion is not None:
        m = sel.motion
        x, y = m.at(mjd)
        line = None
        if m.moving and len(f.visits) > 1:
            ax, ay = m.at(f.visits[0].mjd)
            bx, by = m.at(f.visits[-1].mjd)
            line = [ax, ay, bx, by]
        points = []
        if v.band == sel.band:
            points = [[p.x, p.y, p.visit == v.visit] for p in m.points]
        out["selection"] = {
            "x": x, "y": y, "radii": [sky.APERTURE_RADIUS, sky.ANNULUS_INNER, sky.ANNULUS_OUTER],
            "line": line, "points": points,
        }
    return out
