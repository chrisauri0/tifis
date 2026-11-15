"""Temperatura de color y profundidad de bandas a partir de las medidas de la
app SPHEREx Sky Timeline (evento `select`: lista de {c, v, t, l, f, e, ok}).

Solo necesita numpy. Los flujos de SPHEREx son F_nu (MJy/sr sumado en la
apertura -> mJy), así que el modelo es el cuerpo negro por unidad de
frecuencia, B_nu, no B_lambda.
"""

from __future__ import annotations

import numpy as np

H, C, K = 6.62607015e-34, 2.99792458e8, 1.380649e-23

# (nombre, desde µm, hasta µm). Se excluyen del ajuste del continuo y se mide
# su profundidad. Amplias a propósito: la resolución de SPHEREx es R ~ 40-130.
# Varias moléculas comparten bandas; cuál es depende del tipo de objeto.
BANDS = (
    ("H2O", 1.30, 1.50), ("H2O", 1.75, 2.05), ("CH4/CO", 2.15, 2.50),
    ("H2O (hielo o gas)", 2.90, 3.15), ("CH4", 3.15, 3.45), ("CO2", 4.20, 4.35), ("CO", 4.50, 4.80),
)


def b_nu(lam_um, temp):
    """Planck por unidad de frecuencia, en unidades arbitrarias."""
    lam = np.asarray(lam_um, dtype=float) * 1e-6
    x = H * C / (lam * K * temp)
    with np.errstate(over="ignore"):
        return np.where(x > 700, 0.0, 1 / (lam**3 * np.expm1(np.minimum(x, 700))))


def _fit(lam, flux, err, temps):
    """Mejor T de la malla y su escala (la escala sale exacta por mínimos
    cuadrados para cada T, así que solo se busca en una dimensión)."""
    w = 1 / err**2
    best = (np.inf, None, None)
    for t in temps:
        m = b_nu(lam, t)
        mm = np.sum(w * m * m)
        if mm == 0:
            continue
        s = np.sum(w * flux * m) / mm
        chi2 = np.sum(w * (flux - s * m) ** 2)
        if chi2 < best[0]:
            best = (chi2, t, s)
    return best


# Error sistemático mínimo (fracción del flujo): la apertura de 3 píxeles
# recoge una fracción distinta de la estrella en cada canal, y los errores del
# archivo son solo estadísticos.
SYSTEMATIC = 0.03


def analyze(measurements, mask_bands=True, clip=True, systematic=SYSTEMATIC):
    """measurements: lista de dicts {l, f, e, ok} (como en el evento select)."""
    por_canal = {f"canal {c + 1}": {"medidas": 0, "fiables": 0} for c in range(6)}
    for x in measurements:
        k = f"canal {x['c'] + 1}"
        por_canal[k]["medidas"] += 1
        por_canal[k]["fiables"] += bool(x.get("ok"))
    m = [x for x in measurements if x.get("ok") and x.get("e", 0) > 0 and x.get("f") is not None]
    if len(m) < 5:
        return {"error": "muy pocas medidas fiables (¿fuente saturada o todavía cargando?)",
                "por_canal": por_canal}
    lam = np.array([x["l"] for x in m], dtype=float)
    flux = np.array([x["f"] for x in m], dtype=float)
    err = np.array([x["e"] for x in m], dtype=float)
    err = np.hypot(err, systematic * np.abs(flux))

    cont = np.ones(len(lam), dtype=bool)
    if mask_bands:
        for _, lo, hi in BANDS:
            cont &= ~((lam >= lo) & (lam <= hi))
    if cont.sum() < 5:
        cont[:] = True

    coarse = np.arange(200, 10001, 20.0)
    for _ in range(5 if clip else 1):
        chi2, t, s = _fit(lam[cont], flux[cont], err[cont], coarse)
        if not clip:
            break
        # Lo que cae muy por debajo del continuo es absorción, no continuo.
        model = s * b_nu(lam, t)
        keep = cont & (flux > model - 2 * err)
        if keep.sum() < 5 or keep.sum() == cont.sum():
            break
        cont = keep
    chi2, t, s = _fit(lam[cont], flux[cont], err[cont], np.arange(max(200, t - 40), t + 41, 1.0))
    continuum = s * b_nu(lam, t)

    depths = {}
    for name, lo, hi in BANDS:
        # Solo donde el continuo esperado se habría detectado (S/N > 3); en
        # otro caso la "profundidad" es ruido dividido entre casi cero.
        sel = (lam >= lo) & (lam <= hi) & (continuum > 3 * err)
        if sel.sum() < 2:
            continue
        ratio = flux[sel] / continuum[sel]
        w = (continuum[sel] / err[sel]) ** 2
        d = 1 - np.sum(w * ratio) / np.sum(w)
        key = f"{name} {lo:.2f}-{hi:.2f}"
        depths[key] = round(float(d), 3)
    avisos = []
    canales_ok = sum(1 for v in por_canal.values() if v["fiables"] > 0)
    rango = float(lam.max() - lam.min())
    if canales_ok < 3 or rango < 1.5:
        avisos.append(f"Solo {canales_ok} canal(es) con medidas fiables ({lam.min():.2f}-{lam.max():.2f} µm): "
                      "con un rango tan corto la temperatura no queda determinada.")
    if any(v["medidas"] and not v["fiables"] for v in por_canal.values()):
        avisos.append("Hay canales con medidas pero ninguna fiable: la fuente probablemente satura el detector.")
    if len({v["medidas"] for v in por_canal.values() if v["medidas"]}) > 1 and \
            min(v["medidas"] for v in por_canal.values()) < 0.5 * max(v["medidas"] for v in por_canal.values()):
        avisos.append("Algunos canales tienen muchas menos medidas que otros: puede que aún estuvieran cargando.")
    if cont.sum() < 20:
        avisos.append(f"El continuo se ajustó con solo {int(cont.sum())} puntos.")
    red = chi2 / max(1, cont.sum() - 2)
    if red > 5:
        avisos.append(f"El ajuste es malo (chi² reducido {red:.1f}): objeto variable, saturado o no parecido a un cuerpo negro.")
    return {
        "confiable": not avisos,
        "avisos": avisos,
        "T_color_K": float(t),
        # Pico de B_lambda (ley de Wien). En F_nu el pico está en 5100/T µm.
        "pico_wien_um": round(2897.77 / t, 2),
        "puntos": len(m),
        "puntos_continuo": int(cont.sum()),
        "chi2_reducido": round(float(chi2 / max(1, cont.sum() - 2)), 2),
        "profundidad_bandas": depths,
        "por_canal": por_canal,
    }


if __name__ == "__main__":
    import json
    import sys

    # Uso: python espectro.py seleccion.json   (el JSON del evento select)
    sel = json.load(open(sys.argv[1]))
    print(json.dumps(analyze(sel["measurements"]), indent=2, ensure_ascii=False))
