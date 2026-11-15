"""The test objects of the challenge. Positions are J2000 at epoch J2000 and
proper motions come from Simbad (Gaia DR3, CatWISE for WISE 0855)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .grid import MJD_J2000
from .rand import hash_string
from .source import SED_BROWN_DWARF, SED_MIRA, SED_STAR, SED_Y_DWARF, SED_YOUNG, Source, flux_from_mag


@dataclass
class Target:
    id: str
    name: str
    aliases: list[str]
    band: int  # suggested channel, 0-based
    mode: str  # suggested view mode
    source: Source = field(repr=False)


TARGETS: list[Target] = [
    Target(
        "barnard", "Barnard's Star",
        ["barnard", "estrella de barnard", "gj 699", "barnard's star"], 1, "diff",
        Source(name="Barnard's Star", ra=269.45207696, dec=4.69336497, pmra=-801.551, pmdec=10362.394,
               ref_mjd=MJD_J2000, kind=SED_STAR, temp=3200, flux=flux_from_mag(4.52), ref_lambda=2.2, catalog=True),
    ),
    Target(
        "eps-indi-b", "Epsilon Indi B",
        ["eps ind b", "epsilon indi b", "eps indi b", "ε indi b", "epsilon indi ba"], 2, "diff",
        Source(name="Epsilon Indi Ba+Bb", ra=331.04414659, dec=-56.78284420, pmra=3981.977, pmdec=-2466.832,
               ref_mjd=MJD_J2000, kind=SED_BROWN_DWARF, temp=1100, flux=flux_from_mag(11.21), ref_lambda=2.2,
               catalog=True),
    ),
    Target(
        "wise0855", "WISE 0855-0714",
        ["wise 0855", "wise 0855-0714", "wise j0855", "wisea j085510.74-071442.5", "wise j085510.83-071442.5"], 5, "diff",
        Source(name="WISE 0855-0714", ra=133.81890825, dec=-7.24704800, pmra=-8123.7, pmdec=673.2,
               ref_mjd=MJD_J2000, kind=SED_Y_DWARF, temp=285, flux=flux_from_mag(13.9), ref_lambda=4.6, catalog=True),
    ),
    Target(
        "rw-aur", "RW Aurigae", ["rw aur", "rw aurigae"], 3, "epoch",
        Source(name="RW Aur", ra=76.95652603, dec=30.40143817, pmra=7.23, pmdec=-20.33,
               ref_mjd=MJD_J2000, kind=SED_YOUNG, temp=4500, flux=flux_from_mag(7.02), ref_lambda=2.2,
               amp=0.7, catalog=True),
    ),
    Target(
        "r-dra", "R Draconis", ["r dra", "r draconis"], 2, "epoch",
        # K is 2.2 in reality; the simulation dims it 2 mag so the core only
        # saturates near maximum and the pulsation stays visible.
        Source(name="R Dra", ra=248.16761083, dec=66.75497942, pmra=-20.643, pmdec=6.149,
               ref_mjd=MJD_J2000, kind=SED_MIRA, temp=2600, flux=flux_from_mag(4.2), ref_lambda=2.2,
               period=245.6, amp=0.9, phase=60950, catalog=True),
    ),
]

for _t in TARGETS:
    _t.source.seed = hash_string(_t.id)
