"""Small numeric helpers with the exact semantics the formats and the original
code rely on: rounding half away from zero, strict integer and float parsing."""

from __future__ import annotations

import math
import re

import numpy as np

_INT_RE = re.compile(r"[+-]?[0-9]+")
_FLOAT_RE = re.compile(
    r"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|inf|infinity|nan)",
    re.IGNORECASE,
)


def go_round(x: float) -> float:
    """Round half away from zero (Python's round() rounds half to even)."""
    if not math.isfinite(x):
        return x
    t = math.trunc(x)
    if abs(x - t) >= 0.5:  # x - trunc(x) is exact in floating point
        t += math.copysign(1.0, x)
    return float(t)


def round_array(x: np.ndarray) -> np.ndarray:
    """Vectorised go_round."""
    x = np.asarray(x, dtype=np.float64)
    t = np.trunc(x)
    return t + np.where(np.abs(x - t) >= 0.5, np.sign(x), 0.0)


def parse_int(s: str | bytes) -> int:
    """Base-10 integer with an optional sign and nothing else; ValueError otherwise."""
    if isinstance(s, bytes):
        s = s.decode("ascii", "replace")
    if not _INT_RE.fullmatch(s):
        raise ValueError(f"invalid integer {s!r}")
    return int(s)


def int_or(s: str, default: int) -> int:
    try:
        return parse_int(s)
    except ValueError:
        return default


def parse_float(s: str | bytes) -> float:
    """Decimal float (or inf/nan) without surrounding spaces or underscores."""
    if isinstance(s, bytes):
        s = s.decode("ascii", "replace")
    if not _FLOAT_RE.fullmatch(s):
        raise ValueError(f"invalid float {s!r}")
    return float(s)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
