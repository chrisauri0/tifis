"""Split and join FITS files at the HDU level, and decode the few data types the
SPHEREx cutouts use.

Headers are read but data is left untouched, which is all the proxy needs to
drop an extension: the remaining HDUs are copied byte for byte.
"""

from __future__ import annotations

import numpy as np

from .num import int_or, parse_float, parse_int

BLOCK = 2880
END_CARD = b"END" + b" " * 77


class FitsError(ValueError):
    pass


def padded(n: int) -> int:
    return (n + BLOCK - 1) // BLOCK * BLOCK


class HDU:
    """One header and data unit. Both parts include their padding."""

    __slots__ = ("header", "data")

    def __init__(self, header: bytes, data: bytes = b""):
        self.header = bytes(header)
        self.data = bytes(data)

    def _cards(self):
        h = self.header
        for i in range(0, len(h) - 79, 80):
            yield h[i : i + 80].decode("latin-1")

    def keyword(self, name: str) -> str:
        """Value of a keyword with quotes and comments removed, '' if missing."""
        for card in self._cards():
            if card[:8].strip() != name or card[8:10] != "= ":
                continue
            v = card[10:]
            if v.strip().startswith("'"):
                v = v.strip()
                end = v[1:].find("'")
                if end >= 0:
                    return v[1 : end + 1].strip()
            c = v.find("/")
            if c >= 0:
                v = v[:c]
            return v.strip()
        return ""

    def name(self) -> str:
        return self.keyword("EXTNAME") or "PRIMARY"

    def float(self, name: str, default: float) -> float:
        """Numeric keyword (Fortran D exponents accepted), default when missing or invalid."""
        try:
            return parse_float(self.keyword(name).replace("D", "E"))
        except ValueError:
            return default

    def int(self, name: str, default: int) -> int:
        return int_or(self.keyword(name), default)

    def keywords(self, prefix: str) -> dict[str, str]:
        out = {}
        for card in self._cards():
            name = card[:8].strip()
            if name.startswith(prefix) and card[8:10] == "= ":
                out[name] = self.keyword(name)
        return out

    def data_size(self) -> int:
        try:
            naxis = parse_int(self.keyword("NAXIS"))
        except ValueError:
            raise FitsError(f"fits: bad NAXIS in {self.name()}") from None
        if naxis == 0:
            return 0
        try:
            bitpix = parse_int(self.keyword("BITPIX"))
        except ValueError:
            raise FitsError(f"fits: bad BITPIX in {self.name()}") from None
        size = abs(bitpix) // 8
        for i in range(1, naxis + 1):
            try:
                size *= parse_int(self.keyword(f"NAXIS{i}"))
            except ValueError:
                raise FitsError(f"fits: bad NAXIS{i} in {self.name()}") from None
        g = self.keyword("GCOUNT")
        gcount = int_or(g, 0) if g else 1
        p = self.keyword("PCOUNT")
        pcount = int_or(p, 0) if p else 0
        return gcount * (size + pcount)

    def image(self) -> np.ndarray:
        """2D image as float32, shape (NAXIS2, NAXIS1), first FITS row first.
        BITPIX 32 integer images are converted too."""
        w, h = self.int("NAXIS1", 0), self.int("NAXIS2", 0)
        n = w * h
        bitpix = self.int("BITPIX", 0)
        if self.int("NAXIS", 0) != 2 or n <= 0 or len(self.data) < n * abs(bitpix) // 8:
            raise FitsError(f"fits: {self.name()} is not a 2D image")
        if bitpix == -32:
            a = np.frombuffer(self.data, dtype=">f4", count=n)
        elif bitpix == 32:
            a = np.frombuffer(self.data, dtype=">i4", count=n)
        else:
            raise FitsError(f"fits: unsupported BITPIX {bitpix} in {self.name()}")
        return a.astype(np.float32).reshape(h, w)

    def uint32_image(self) -> np.ndarray:
        """BITPIX 32 image read bit for bit, as needed for flag masks."""
        w, h = self.int("NAXIS1", 0), self.int("NAXIS2", 0)
        n = w * h
        if self.int("BITPIX", 0) != 32 or self.int("NAXIS", 0) != 2 or n <= 0 or len(self.data) < 4 * n:
            raise FitsError(f"fits: {self.name()} is not a 32-bit 2D image")
        return np.frombuffer(self.data, dtype=">u4", count=n).astype(np.uint32).reshape(h, w)

    def column(self, name: str) -> np.ndarray:
        """One column of the first row of a binary table, as float64.
        Only the J, E and D formats used by SPHEREx tables are decoded."""
        if self.keyword("XTENSION") != "BINTABLE":
            raise FitsError(f"fits: {self.name()} is not a binary table")
        sizes = {"J": 4, "E": 4, "D": 8, "I": 2, "B": 1, "L": 1}
        off = 0
        for i in range(1, self.int("TFIELDS", 0) + 1):
            form = self.keyword(f"TFORM{i}")
            count, kind = 1, form
            j = min((form.find(c) for c in "JEDIBL" if c in form), default=-1)
            if j > 0:
                count = int_or(form[:j], 0)
                kind = form[j:]
            size = sizes.get(kind[:1], 0)
            if self.keyword(f"TTYPE{i}").casefold() != name.casefold():
                off += count * size
                continue
            if off + count * size > len(self.data):
                raise FitsError(f"fits: column {name} out of range")
            dtype = {"J": ">i4", "E": ">f4", "D": ">f8"}.get(kind[:1])
            if dtype is None:
                raise FitsError(f"fits: unsupported column format {form}")
            return np.frombuffer(self.data, dtype=dtype, count=count, offset=off).astype(np.float64)
        raise FitsError(f"fits: no column {name} in {self.name()}")


def parse(data: bytes) -> list[HDU]:
    """Split a FITS file into its HDUs."""
    if len(data) < BLOCK or not data.startswith(b"SIMPLE  ="):
        raise FitsError("fits: not a FITS file")
    hdus = []
    off = 0
    while off < len(data):
        start = off
        end = -1
        while end < 0:
            if off + BLOCK > len(data):
                raise FitsError("fits: truncated header")
            for i in range(off, off + BLOCK, 80):
                if data[i : i + 80] == END_CARD:
                    end = i
                    break
            off += BLOCK
        h = HDU(data[start:off])
        size = padded(h.data_size())
        if off + size > len(data):
            raise FitsError(f"fits: truncated data in {h.name()}")
        h.data = bytes(data[off : off + size])
        off += size
        hdus.append(h)
    return hdus


def join(hdus: list[HDU]) -> bytes:
    """Write HDUs back into a FITS file."""
    return b"".join(h.header + h.data for h in hdus)


def find(hdus: list[HDU], name: str) -> HDU | None:
    for h in hdus:
        if h.name() == name:
            return h
    return None
