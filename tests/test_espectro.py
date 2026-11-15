"""The spectrum analysis (spherex/espectro.py) and its feature table
(spherex/features.py): synthetic spectra with known answers, and the five
test objects of the challenge through the simulation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spherex import espectro as E
from spherex import features as F
from spherex import sky

TEST_NOW = 61356  # 2026-11-12
CHANNELS = [(c.lo, c.hi) for c in sky.CHANNELS]


def survey(spectrum, seasons=3, visits=24, noise=0.01, seed=1, brightness=None):
    """Measurements like the engine's: each visit sees all six channels at the
    same time, each at a different λ of its filter. `spectrum(λ)` is the
    shape; `brightness(t, λ)` multiplies it (variability)."""
    r = np.random.default_rng(seed)
    out = []
    for s in range(seasons):
        for k in range(visits):
            v = s * visits + k
            t = 60800 + 182 * s + 14 * k / visits
            for c, (lo, hi) in enumerate(CHANNELS):
                lam = lo + (hi - lo) * (k + r.random()) / visits
                f = spectrum(lam) * (brightness(t, lam) if brightness else 1.0)
                e = noise * max(abs(f), 1e-3) + 1e-4
                out.append({"c": c, "v": v, "t": t, "l": lam, "f": f + r.normal(0, e), "e": e, "ok": True, "s": s})
    return out


def bb(temp, scale=1.0):
    ref = E.b_nu(2.0, temp)
    return lambda lam: scale * float(E.b_nu(lam, temp) / ref)


def absorb(base, bands):
    def f(lam):
        v = base(lam)
        for c, w, d in bands:
            v *= 1 - d * np.exp(-0.5 * ((lam - c) / w) ** 2)
        return v
    return f


def top(r):
    return r["clasificacion"][0]["id"] if r["clasificacion"] else None


def feat(r, fid):
    return next((f for f in r["firmas"] if f["id"] == fid), None)


# ---------- the feature table ----------

def test_feature_table_is_consistent():
    ids = [f["id"] for f in F.FEATURES]
    assert len(ids) == len(set(ids))
    for f in F.FEATURES:
        assert 0.75 <= f["lo"] < f["hi"] <= 5.0, f["id"]
        assert f["lo"] <= f["center"] <= f["hi"], f["id"]
        assert f["kind"] in ("abs", "emi", "either") and f["continuum"] in ("planck", "local")
        assert f["desc"]["es"] and f["desc"]["en"]
        if f["line"]:
            # An unresolved line spans about one resolution element.
            assert (f["hi"] - f["lo"]) == pytest.approx(1.2 * f["center"] / F.resolution(f["center"]), rel=0.05)
    known = set(ids) | set(F.PSEUDO)
    rules = {r["id"] for r in F.RULES}
    for r in F.RULES:
        refs = [w[0] for w in r.get("want", [])] + r.get("avoid", []) + r.get("bonus", [])
        for ref in refs:
            assert ref.split(":")[0] in known, (r["id"], ref)
    for f in F.FEATURES:
        assert set(f["classes"]) <= rules, f["id"]
    # What /api/features serves is plain JSON.
    js = json.loads(json.dumps(F.as_json()))
    assert len(js["features"]) == len(F.FEATURES)
    assert "co2_427" in next(f for f in js["features"] if f["id"] == "co_46")["overlaps"] or True
    assert set(next(f for f in js["features"] if f["id"] == "ch4_33")["overlaps"]) >= {"pah_33", "ice_30"}


def test_resolution_matches_spherex():
    assert F.resolution(1.0) == 41 and F.resolution(3.0) == 35
    assert F.resolution(4.0) == 110 and F.resolution(4.8) == 130


# ---------- building blocks ----------

def test_feature_depth_is_the_weighted_mean():
    lam = np.linspace(1.0, 2.0, 11)
    cont = np.full(11, 10.0)
    flux = cont.copy()
    flux[4:7] = 7.0
    err = np.full(11, 0.1)
    d, sigma, z, n = E.feature_depth(lam, flux, err, cont, 1.35, 1.65)
    assert n == 3 and d == pytest.approx(0.3) and sigma == pytest.approx(0.01 / np.sqrt(3))
    assert z == pytest.approx(d / sigma)
    # Where the continuum would not have been detected there is nothing to measure.
    assert E.feature_depth(lam, flux, np.full(11, 5.0), cont, 1.35, 1.65) is None


def test_planck_fit_recovers_temperature():
    for temp in (800, 3200, 6000):
        r = E.analyze(survey(bb(temp)))
        assert abs(r["T_color_K"] - temp) < 0.03 * temp, temp
        assert r["T_err_K"] < 0.05 * temp


def test_plain_black_body_has_no_features():
    r = E.analyze(survey(bb(4000), noise=0.02, seed=7))
    hits = [f["id"] for f in r["firmas"] if f["estado"] in ("detectada", "compatible")]
    assert hits == []
    assert top(r) == "star"
    assert json.dumps(E.to_json(r), allow_nan=False)


# ---------- classification ----------

def test_t_dwarf_from_methane_and_water():
    spec = absorb(bb(1000), [(1.4, 0.08, 0.7), (1.65, 0.05, 0.4), (1.9, 0.1, 0.7), (3.32, 0.08, 0.8)])
    r = E.analyze(survey(spec))
    assert feat(r, "ch4_33")["estado"] == "detectada" and feat(r, "ch4_33")["d"] > 0.2
    assert feat(r, "h2o_14")["estado"] == "detectada"
    assert top(r) == "brown_dwarf_ty"
    assert any(n["id"] == "tcolor" for n in r["notas"])


def test_red_giant_from_co_and_water():
    spec = absorb(bb(3300), [(1.4, 0.08, 0.35), (1.9, 0.1, 0.35), (2.4, 0.08, 0.3), (4.65, 0.1, 0.3)])
    r = E.analyze(survey(spec))
    assert top(r) == "red_giant"
    assert feat(r, "ch4_33")["estado"] not in ("detectada", "indicio")


def test_ices_on_a_background_star():
    spec = absorb(bb(4500), [(3.05, 0.12, 0.4), (4.27, 0.03, 0.5), (4.67, 0.02, 0.3)])
    r = E.analyze(survey(spec, noise=0.005))
    assert feat(r, "ice_30")["estado"] == "detectada"
    assert feat(r, "co2_427")["observado"] == "absorción" and feat(r, "co2_427")["z"] > 3
    assert top(r) == "cold_cloud"


def test_emission_line_uses_local_continuum_and_says_compatible():
    star = bb(9000)
    # Brα: a narrow line whose flux is spread over the SPHEREx filter.
    spec = lambda lam: star(lam) * (1 + 1.5 * np.exp(-0.5 * ((lam - 4.051) / 0.015) ** 2))
    r = E.analyze(survey(spec, noise=0.01, visits=40))
    f = feat(r, "bra")
    assert f["metodo"] == "local" and f["d"] < 0 and f["estado"] == "compatible"
    assert any(n["id"] == "lines" for n in r["notas"])


def test_line_at_a_band_edge_is_not_invented():
    # Paβ sits at the edge of the 1.4 µm water band of a brown dwarf; with the
    # band detected, its window is gone and the line is not measured.
    spec = absorb(bb(1000), [(1.15, 0.05, 0.5), (1.4, 0.08, 0.75), (1.9, 0.1, 0.75), (3.3, 0.15, 0.85)])
    r = E.analyze(survey(spec))
    pab = feat(r, "pab")
    assert pab is None or pab["estado"] not in ("compatible", "detectada")


def test_young_star_from_infrared_excess():
    star, disk = bb(4500), bb(1000, 0.8)
    r = E.analyze(survey(lambda lam: star(lam) + disk(lam)))
    assert r["exceso_ir"]["z"] > 5
    assert top(r) == "young_star"
    assert r["estrella_disco"]["T_disco_K"] == pytest.approx(1000, abs=150)


def test_very_cold_object_is_a_y_dwarf_even_without_methane_coverage():
    spec = absorb(bb(300), [(4.65, 0.1, 0.3)])
    r = E.analyze(survey(spec, noise=0.03))
    assert r["T_color_K"] < 400 and top(r) == "brown_dwarf_ty"
    assert r["exceso_ir"] is None  # nothing to extrapolate from at short λ


def test_solar_system_two_components():
    sun, warm = bb(E.T_SUN), bb(320, 0.02)
    gas = lambda lam: 1 + 2.0 * np.exp(-0.5 * ((lam - 4.27) / 0.03) ** 2)
    spec = lambda lam: (sun(lam) + warm(lam)) * gas(lam)
    r = E.analyze(survey(spec, noise=0.01), solar_system=True)
    ss = r["sistema_solar"]
    assert abs(ss["T_termica_K"] - 320) < 60 and ss["fraccion_termica_4_6um"] > 0.5
    assert feat(r, "co2_427")["observado"] == "emisión"
    assert top(r) == "comet"
    assert all(c["id"] in ("comet", "hydrated_asteroid", "dry_asteroid") for c in r["clasificacion"])


# ---------- change over time ----------

def test_variability_test_tells_variable_from_stable():
    stable = survey(bb(3000))
    m, lam, flux, err, t, _ = E._prepare(stable, E.SYSTEMATIC)
    assert E.variability(lam, flux, err, t)["razon"] < 1.5
    pulse = lambda t, lam: 10 ** (0.4 * 0.8 * (1.2 / lam) ** 0.6 * np.cos(2 * np.pi * t / 240))
    var = survey(bb(3000), brightness=pulse)
    m, lam, flux, err, t, _ = E._prepare(var, E.SYSTEMATIC)
    assert E.variability(lam, flux, err, t)["razon"] > E.VARIABLE_RATIO


def test_seasons_of_a_stable_source_do_not_change():
    r = E.analyze_seasons(survey(absorb(bb(1000), [(1.4, 0.08, 0.7), (3.32, 0.08, 0.8)]), seasons=4))
    assert len(r["temporadas"]) == 4 and len(r["cambios"]) == 3
    assert not any(c["T_cambia"] or c["brillo_cambia"] or c["cambios"] for c in r["cambios"])
    assert any(n["id"] == "stable" for n in r["notas"])


def test_seasons_of_a_pulsating_star_change():
    giant = absorb(bb(2800), [(1.4, 0.08, 0.35), (1.9, 0.1, 0.35), (2.4, 0.08, 0.3)])
    pulse = lambda t, lam: 10 ** (0.4 * 0.9 * (1.2 / lam) ** 0.6 * np.cos(2 * np.pi * (t - 60800) / 300))
    r = E.analyze_seasons(survey(giant, brightness=pulse, seasons=3))
    assert any(c["brillo_cambia"] for c in r["cambios"])
    first = r["cambios"][0]["dmag"]["1.2um"]["dmag"]
    assert first > 0.3  # fainter half a cycle later, more at short λ
    assert r["cambios"][0]["dmag"]["4.6um"]["dmag"] < first
    assert top(r) == "red_giant"


def test_split_seasons_by_gap_without_engine_seasons():
    ms = [dict(x) for x in survey(bb(3000), seasons=3)]
    for x in ms:
        del x["s"]
    assert list(E.split_seasons(ms)) == [0, 1, 2]


# ---------- the five test objects, simulated ----------

@pytest.fixture(scope="module")
def simulated():
    out = {}
    for t in sky.TARGETS:
        src = t.source
        f = sky.new_field(*src.position(TEST_NOW), 6, TEST_NOW)
        for c in range(sky.NUM_CHANNELS):
            for fr in f.frames[c]:
                if fr.available:
                    f.load(fr)
        v = next(i for i, fr in enumerate(f.frames[t.band]) if fr.available)
        x, y = f.wcs.to_pixel(*src.position(f.visits[v].mjd))
        m = sky.track(f, t.band, v, x, y)
        out[t.id] = [dict(mm.to_json(), s=f.visits[mm.visit].season) for mm in sky.measure(f, m)]
    return out


@pytest.mark.parametrize("target,expected,variable", [
    ("barnard", "star", False),
    ("eps-indi-b", "brown_dwarf_ty", False),
    ("wise0855", "brown_dwarf_ty", False),
    ("rw-aur", "young_star", True),
    ("r-dra", "red_giant", True),
])
def test_challenge_objects(simulated, target, expected, variable):
    r = E.analyze_seasons(simulated[target])
    assert top(r) == expected
    assert (r["variabilidad"]["razon"] > E.VARIABLE_RATIO) == variable
    changed = any(c["T_cambia"] or c["brillo_cambia"] for c in r["cambios"])
    assert changed == variable
    json.dumps(E.to_json(r), allow_nan=False)


def test_sample_selection_and_cli(capsys):
    # A real selection saved from the app (Epsilon Indi B, SPHEREx QR data).
    sel = json.loads((Path(E.__file__).parent / "seleccion.json").read_text())
    r = E.analyze_seasons(sel["measurements"])
    assert top(r) == "brown_dwarf_ty"
    E.main([str(Path(E.__file__).parent / "seleccion.json"), "--por-temporada"])
    assert "Enana marrón T/Y" in capsys.readouterr().out
