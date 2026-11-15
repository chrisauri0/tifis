"""Deterministic randomness for the simulation: a field always looks the same."""

from __future__ import annotations

import numpy as np

MASK64 = (1 << 64) - 1
_FNV_OFFSET = 14695981039346656037
_FNV_PRIME = 1099511628211


def hash_string(s: str) -> int:
    """64-bit FNV-1a of the UTF-8 bytes of s."""
    h = _FNV_OFFSET
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & MASK64
    return h


def new_rand(seed: int) -> np.random.Generator:
    seed &= MASK64
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, seed ^ 0x9E3779B97F4A7C15])))
