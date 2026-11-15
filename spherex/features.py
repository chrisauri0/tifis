"""Spectral features SPHEREx can see, and the rules that turn them into a
guess of what the object is. This is the single source of truth: the
analysis in `espectro.py` reads it, and the server hands it to the page at
`/api/features`, which draws the bands from it.

Wavelengths are laboratory values (vacuum, µm) of the strongest features in
0.75-5 µm. Band edges are wider than the features on purpose: they have to
hold at least a couple of SPHEREx measurements, and SPHEREx resolves only
λ/Δλ ≈ 35-130 (see `resolution`). Unresolved lines (`line=True`) get edges
of ±0.6 resolution elements around the line, so they come out as bumps, not
as lines, and are reported as "compatible with", never as "detected".

`kind` is the sign the feature normally has: "abs" (absorption, flux below
the continuum), "emi" (emission) or "either" (CO₂ at 4.27 µm is ice
absorption in clouds and gas emission in comet comae). `continuum` is how
the depth is measured: "planck" against the fitted black body, "local"
against a straight line through windows on each side, which is the right
reference for emission and for anything on top of a spectrum that is not a
black body (PAHs, nebulae).

References for the wavelengths: Cushing et al. 2005 (ApJ 623, 1115) and
Kirkpatrick 2005 (ARA&A 43, 195) for brown dwarfs; Boogert, Gerakines &
Whittet 2015 (ARA&A 53, 541) for ices; Tielens 2008 (ARA&A 46, 289) for
PAHs; NIST Atomic Spectra Database for H I and He I; Doré et al. 2014
(arXiv:1412.4872) and the SPHEREx Explanatory Supplement for resolution.
"""

from __future__ import annotations

# λ/Δλ of each SPHEREx channel: (from µm, to µm, R).
RESOLUTION = ((0.75, 2.42, 41), (2.42, 3.82, 35), (3.82, 4.42, 110), (4.42, 5.00, 130))


def resolution(lam: float) -> float:
    for lo, hi, r in RESOLUTION:
        if lo <= lam < hi:
            return r
    return RESOLUTION[0][2] if lam < RESOLUTION[0][0] else RESOLUTION[-1][2]


def _line(lam: float) -> tuple[float, float]:
    """Edges of an unresolved line: ±0.6 resolution elements."""
    half = 0.6 * lam / resolution(lam)
    return round(lam - half, 3), round(lam + half, 3)


def _f(id, species, label, lo, hi, kind, classes, desc, confuses=None, center=None, line=False,
       continuum=None):
    return {
        "id": id, "species": species, "label": label, "lo": lo, "hi": hi,
        "center": round(center if center is not None else (lo + hi) / 2, 4),
        "kind": kind, "line": line,
        "continuum": continuum or ("planck" if kind == "abs" else "local"),
        "classes": classes, "confuses": confuses, "desc": desc,
    }


def _l(id, species, label, lam, classes, desc, confuses=None):
    lo, hi = _line(lam)
    return _f(id, species, label, lo, hi, "emi", classes, desc, confuses, center=lam, line=True)


FEATURES: list[dict] = [
    # ---------- Molecules in cool atmospheres (absorption) ----------
    _f("h2o_14", "H₂O", "H₂O", 1.30, 1.50, "abs", ["brown_dwarf_ty", "brown_dwarf_l", "red_giant"],
       {"es": "Vapor de agua en atmósferas frías: enanas marrones, enanas M y gigantes rojas.",
        "en": "Water vapor in cool atmospheres: brown dwarfs, M dwarfs and red giants."},
       {"es": "En enanas T el metano a 1.4 µm se suma al agua.",
        "en": "In T dwarfs, methane at 1.4 µm adds to the water."}),
    _f("ch4_165", "CH₄", "CH₄", 1.60, 1.80, "abs", ["brown_dwarf_ty"],
       {"es": "Metano a 1.65 µm: solo aparece por debajo de ~1300 K, en enanas marrones T y Y.",
        "en": "Methane at 1.65 µm: it appears only below ~1300 K, in T and Y brown dwarfs."},
       {"es": "El borde del agua de 1.9 µm empieza en 1.75 µm.",
        "en": "The edge of the 1.9 µm water band starts at 1.75 µm."}),
    _f("h2o_19", "H₂O", "H₂O", 1.75, 2.05, "abs", ["brown_dwarf_ty", "brown_dwarf_l", "red_giant"],
       {"es": "Más vapor de agua; en enanas marrones casi apaga la luz aquí.",
        "en": "More water vapor; in brown dwarfs it nearly blacks out the light here."},
       {"es": "La línea Paα (1.875 µm, emisión) cae dentro de esta banda.",
        "en": "The Paα line (1.875 µm, emission) falls inside this band."}),
    _f("ch4_22", "CH₄", "CH₄", 2.15, 2.29, "abs", ["brown_dwarf_ty"],
       {"es": "Metano a 2.2 µm, junto con hidrógeno molecular inducido por colisiones, en enanas T.",
        "en": "Methane at 2.2 µm, plus collision-induced H₂, in T dwarfs."},
       {"es": "Se junta con el CO desde 2.29 µm y con la línea Brγ (2.166 µm).",
        "en": "It runs into CO from 2.29 µm on and overlaps the Brγ line (2.166 µm)."}),
    _f("co_23", "CO", "CO", 2.29, 2.50, "abs", ["red_giant", "brown_dwarf_l"],
       {"es": "Monóxido de carbono (bandas de 2.29 µm) en gigantes rojas frías y enanas L.",
        "en": "Carbon monoxide (2.29 µm bandheads) in cool red giants and L dwarfs."},
       {"es": "El metano también absorbe en 2.2-2.4 µm.",
        "en": "Methane also absorbs at 2.2-2.4 µm."}),
    _f("h2o_27", "H₂O", "H₂O", 2.55, 2.85, "abs", ["brown_dwarf_ty", "brown_dwarf_l", "red_giant"],
       {"es": "La banda más fuerte del vapor de agua, a 2.7 µm. Desde la Tierra no se ve: la absorbe nuestra atmósfera.",
        "en": "The strongest water-vapor band, at 2.7 µm. It cannot be seen from the ground: our atmosphere absorbs it."},
       {"es": "Su ala larga se confunde con el hielo de agua de 3.0 µm.",
        "en": "Its long wing blends with the 3.0 µm water ice."}),
    _f("ch4_33", "CH₄", "CH₄", 3.20, 3.45, "abs", ["brown_dwarf_ty"],
       {"es": "La banda fundamental del metano, la firma más clara de las enanas marrones T y Y.",
        "en": "The fundamental methane band, the clearest signature of T and Y brown dwarfs."},
       {"es": "En nebulosas y galaxias, a 3.3 µm brillan moléculas orgánicas (PAH): emisión, no absorción.",
        "en": "In nebulae and galaxies, organic molecules (PAHs) glow at 3.3 µm: emission, not absorption."}),
    _f("co_46", "CO", "CO", 4.45, 4.85, "abs", ["red_giant", "brown_dwarf_l", "brown_dwarf_ty"],
       {"es": "Monóxido de carbono gaseoso (banda fundamental). En enanas Y indica que el gas se mezcla desde capas calientes.",
        "en": "Gaseous carbon monoxide (fundamental band). In Y dwarfs it means gas is mixed up from hot layers."},
       {"es": "El hielo de CO absorbe a 4.67 µm, en medio de esta banda.",
        "en": "CO ice absorbs at 4.67 µm, in the middle of this band."}),
    # ---------- Ices in cold clouds (absorption) ----------
    _f("ice_30", "H₂O ❄", "H₂O ❄", 2.90, 3.25, "abs", ["cold_cloud", "hydrated_asteroid"],
       {"es": "Hielo de agua sobre granos de polvo en nubes frías; se ve como absorción en la luz de estrellas de fondo. En asteroides indica minerales hidratados.",
        "en": "Water ice on dust grains in cold clouds; seen as absorption in the light of background stars. On asteroids it means hydrated minerals."},
       {"es": "El vapor de agua (2.7 µm) y los minerales hidratados absorben cerca.",
        "en": "Water vapor (2.7 µm) and hydrated minerals absorb nearby."}),
    _f("co2_427", "CO₂", "CO₂", 4.20, 4.35, "either", ["cold_cloud", "comet"],
       {"es": "Dióxido de carbono: hielo en nubes frías (absorción) o gas en la coma de un cometa (emisión).",
        "en": "Carbon dioxide: ice in cold clouds (absorption) or gas in a comet's coma (emission)."},
       {"es": "Hielo y gas caen en la misma longitud de onda; el signo (absorción o emisión) los separa.",
        "en": "Ice and gas sit at the same wavelength; the sign (absorption or emission) tells them apart."},
       center=4.27),
    _f("co_ice_467", "CO ❄", "CO ❄", 4.63, 4.71, "abs", ["cold_cloud"],
       {"es": "Hielo de monóxido de carbono: solo existe por debajo de ~20 K, en el corazón de las nubes.",
        "en": "Carbon monoxide ice: it exists only below ~20 K, deep inside clouds."},
       {"es": "Cae dentro de la banda del CO gaseoso.",
        "en": "It falls inside the band of gaseous CO."},
       center=4.67, continuum="local"),
    # ---------- Emission: ionized gas, accretion, organics ----------
    _l("hei_108", "He I", "He I", 1.083, ["young_star"],
       {"es": "Helio: vientos y acreción en estrellas jóvenes.",
        "en": "Helium: winds and accretion in young stars."},
       {"es": "A esta resolución se mezcla con Paγ (1.094 µm).",
        "en": "At this resolution it blends with Paγ (1.094 µm)."}),
    _l("pab", "H I Paβ", "Paβ", 1.282, ["young_star", "nebula"],
       {"es": "Hidrógeno (Paschen β): gas ionizado o que cae sobre una estrella joven.",
        "en": "Hydrogen (Paschen β): ionized gas, or gas falling onto a young star."}),
    _l("paa", "H I Paα", "Paα", 1.875, ["young_star", "nebula"],
       {"es": "Hidrógeno (Paschen α), la línea más brillante del hidrógeno en el infrarrojo cercano.",
        "en": "Hydrogen (Paschen α), the brightest hydrogen line in the near infrared."},
       {"es": "Cae dentro de la banda de agua de 1.9 µm.",
        "en": "It falls inside the 1.9 µm water band."}),
    _l("h2_212", "H₂", "H₂", 2.122, ["young_star"],
       {"es": "Hidrógeno molecular calentado por choques: chorros de estrellas recién nacidas.",
        "en": "Molecular hydrogen heated by shocks: jets from newborn stars."},
       {"es": "A esta resolución se mezcla con Brγ (2.166 µm).",
        "en": "At this resolution it blends with Brγ (2.166 µm)."}),
    _l("brg", "H I Brγ", "Brγ", 2.166, ["young_star", "nebula"],
       {"es": "Hidrógeno (Brackett γ): el indicador clásico de acreción en estrellas jóvenes.",
        "en": "Hydrogen (Brackett γ): the classic accretion tracer in young stars."},
       {"es": "Se mezcla con H₂ (2.122 µm) y con el metano de 2.2 µm.",
        "en": "It blends with H₂ (2.122 µm) and 2.2 µm methane."}),
    _f("pah_33", "PAH", "PAH", 3.24, 3.35, "emi", ["nebula"],
       {"es": "Moléculas orgánicas grandes (PAH) que brillan al recibir luz ultravioleta, en nebulosas y galaxias.",
        "en": "Large organic molecules (PAHs) that glow under ultraviolet light, in nebulae and galaxies."},
       {"es": "En enanas marrones el metano absorbe justo aquí.",
        "en": "In brown dwarfs, methane absorbs right here."},
       center=3.29),
    _l("bra", "H I Brα", "Brα", 4.051, ["nebula", "young_star"],
       {"es": "Hidrógeno ionizado por estrellas jóvenes y calientes (nebulosas): una línea de emisión.",
        "en": "Hydrogen ionized by young, hot stars (nebulae): an emission line."}),
]

BY_ID = {f["id"]: f for f in FEATURES}

# Pseudo-features measured from the whole spectrum instead of one band.
#   ir_excess: light at 3.8-5 µm above the black body fitted to < 2.3 µm
#              (warm dust: disks around young stars).
#   very_cold: color temperature below 700 K: only Y dwarfs (and solar-system
#              bodies) are that cold.
#   thermal:   thermal emission in the two-component (reflected sunlight +
#              thermal) model of solar-system bodies.
PSEUDO = {
    "ir_excess": {"es": "exceso infrarrojo (polvo tibio)", "en": "infrared excess (warm dust)"},
    "very_cold": {"es": "temperatura de color < 700 K", "en": "color temperature < 700 K"},
    "thermal": {"es": "emisión térmica propia", "en": "own thermal emission"},
}

# Rules: the color temperature says which families are plausible (`T`, K;
# None means any; the edges are soft), the features confirm them. `want` is
# [(feature, weight)], where a feature can carry the sign it must have
# ("co2_427:emi"); the score is their weighted mean, times a coverage factor
# when some of them could not be measured. `bonus` features raise the score
# if present but do not count against it if absent. `avoid` lowers the
# score when those features are present. `base` scores a rule with nothing
# to want (a plain black body). `solar_system` rules only run with the
# two-component model.
RULES: list[dict] = [
    {"id": "brown_dwarf_ty", "T": (200, 2000),
     "want": [("ch4_33", 2), ("ch4_165", 1), ("h2o_14", 1), ("h2o_19", 1), ("very_cold", 2)],
     "bonus": ["co_46"],
     "name": {"es": "Enana marrón T/Y", "en": "T/Y brown dwarf"},
     "desc": {"es": "Fría (< 1300 K): metano y agua en la atmósfera.",
              "en": "Cold (< 1300 K): methane and water in the atmosphere."}},
    {"id": "brown_dwarf_l", "T": (1100, 2300),
     "want": [("h2o_14", 2), ("co_23", 1), ("h2o_19", 1)], "avoid": ["ch4_33", "ch4_165"],
     "name": {"es": "Enana L o M tardía", "en": "L or late-M dwarf"},
     "desc": {"es": "Agua y CO, pero sin metano todavía.", "en": "Water and CO, but no methane yet."}},
    {"id": "red_giant", "T": (2000, 4500),
     "want": [("co_23", 2), ("h2o_19", 1), ("h2o_14", 1)], "avoid": ["ch4_33"],
     "name": {"es": "Gigante roja (o estrella M fría)", "en": "Red giant (or cool M star)"},
     "desc": {"es": "Estrella fría y extendida: CO y agua en su atmósfera.",
              "en": "Cool, extended star: CO and water in its atmosphere."}},
    {"id": "cold_cloud", "T": None,
     "want": [("ice_30", 2), ("co2_427:abs", 2), ("co_ice_467", 1)],
     "avoid": ["ch4_165", "very_cold"],
     "name": {"es": "Detrás de una nube fría con hielo", "en": "Behind a cold, icy cloud"},
     "desc": {"es": "La luz atraviesa polvo con hielo de agua, CO₂ y CO.",
              "en": "The light crosses dust coated in water, CO₂ and CO ice."}},
    {"id": "young_star", "T": None,
     "want": [("ir_excess", 1)], "bonus": ["brg", "pab", "paa", "hei_108", "bra", "h2_212"],
     "name": {"es": "Estrella joven con disco", "en": "Young star with a disk"},
     "desc": {"es": "Exceso infrarrojo del disco y, si hay acreción, líneas de hidrógeno y helio.",
              "en": "Infrared excess from the disk and, if it is accreting, hydrogen and helium lines."}},
    {"id": "nebula", "T": None,
     "want": [("pah_33", 2), ("bra", 2), ("paa", 1), ("brg", 1)],
     "name": {"es": "Nebulosa o galaxia con estrellas naciendo", "en": "Nebula or star-forming galaxy"},
     "desc": {"es": "Gas ionizado (hidrógeno) y moléculas orgánicas (PAH) en emisión.",
              "en": "Ionized gas (hydrogen) and organic molecules (PAHs) in emission."}},
    {"id": "star", "T": (2300, 50000), "base": 0.6,
     "avoid": ["h2o_14", "h2o_19", "co_23", "ch4_33", "ice_30", "ir_excess", "pah_33", "bra"],
     "name": {"es": "Estrella sin firmas fuertes", "en": "Star without strong features"},
     "desc": {"es": "El continuo se parece a un cuerpo negro.", "en": "The continuum looks like a black body."}},
    {"id": "comet", "T": None, "solar_system": True,
     "want": [("co2_427:emi", 2), ("thermal", 1), ("ice_30", 1)],
     "name": {"es": "Cometa", "en": "Comet"},
     "desc": {"es": "Luz del Sol reflejada, calor propio y gas de CO₂ en la coma.",
              "en": "Reflected sunlight, its own heat and CO₂ gas in the coma."}},
    {"id": "hydrated_asteroid", "T": None, "solar_system": True,
     "want": [("ice_30", 2), ("thermal", 1)], "avoid": ["co2_427:emi"],
     "name": {"es": "Asteroide hidratado", "en": "Hydrated asteroid"},
     "desc": {"es": "Luz del Sol reflejada con absorción de agua en sus minerales.",
              "en": "Reflected sunlight with water absorption in its minerals."}},
    {"id": "dry_asteroid", "T": None, "solar_system": True, "base": 0.6,
     "avoid": ["ice_30", "co2_427:emi"],
     "name": {"es": "Asteroide seco", "en": "Dry asteroid"},
     "desc": {"es": "Luz del Sol reflejada sin bandas de agua.", "en": "Reflected sunlight without water bands."}},
]

RULES_BY_ID = {r["id"]: r for r in RULES}


def overlaps(fid: str) -> list[str]:
    """Other features whose bands overlap this one."""
    a = BY_ID[fid]
    return [b["id"] for b in FEATURES if b["id"] != fid and b["lo"] < a["hi"] and a["lo"] < b["hi"]]


def as_json() -> dict:
    """What `/api/features` serves: the features (with the overlaps worked
    out), the rules and the resolution of each channel."""
    return {
        "features": [dict(f, overlaps=overlaps(f["id"]), resolution=resolution(f["center"])) for f in FEATURES],
        "rules": [{k: (list(v) if isinstance(v, tuple) else v) for k, v in r.items()} for r in RULES],
        "pseudo": PSEUDO,
        "resolution": [list(r) for r in RESOLUTION],
    }
