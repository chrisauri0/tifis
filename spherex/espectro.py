"""Qué dice el espectro de una fuente: continuo, firmas y clasificación.

Lee las medidas de la app (evento `select`: lista de {c, v, t, l, f, e, ok},
y `s`, la temporada, si el motor la conoce). Solo necesita numpy.

Tres capas:

1. Continuo. Un cuerpo negro (B_nu, porque SPHEREx mide F_nu) ajustado fuera
   de las firmas da la temperatura de color. La química aparece como
   desviación de ese continuo: r(λ) = F_obs / F_Planck, r < 1 es absorción y
   r > 1 emisión. Para líneas de emisión y PAH un cuerpo negro es mal
   continuo, así que ahí se usa uno local: una recta entre dos ventanas a
   cada lado de la firma.
2. Firmas. La profundidad de cada banda de `features.py` con su error y su
   significancia z = d/σ (pesos de varianza inversa). z > 3 es firma real;
   las líneas que SPHEREx no resuelve se reportan como «compatible con».
3. Clasificación. Reglas: la temperatura de color decide qué familias son
   plausibles y las firmas las confirman. Sale una lista ordenada con
   puntajes, no un veredicto.

Los cuerpos del sistema solar no son un solo cuerpo negro: con
`solar_system=True` el continuo es luz del Sol reflejada más emisión térmica.

El cambio en el tiempo sale de repetir todo por temporada
(`analyze_seasons`, `compare_epochs`).

Uso: python -m spherex.espectro seleccion.json [--por-temporada] [--sistema-solar]
"""

from __future__ import annotations

import numpy as np

from .features import BY_ID, FEATURES, RULES, resolution

HC_K = 14387.77  # hc/k en µm·K
T_SUN = 5800.0
# Error sistemático mínimo (fracción del flujo): la apertura de 3 píxeles
# recoge una fracción distinta de la estrella en cada canal, y los errores del
# archivo son solo estadísticos.
SYSTEMATIC = 0.03
# Días sin visitas que separan dos temporadas (igual que sky.real.SEASON_GAP).
SEASON_GAP = 40.0
Z_DETECT = 3.0  # firma real
Z_HINT = 2.0  # indicio
# Un cambio entre temporadas cuenta si supera 3σ. Con ~17 firmas por par de
# temporadas, 2σ daría casi siempre algún «cambio» que es solo ruido.
Z_CHANGE = 3.0
MIN_POINTS = 5
TEMPS = np.arange(200, 10001, 20.0)


def _msg(id_, es, en):
    return {"id": id_, "es": es, "en": en}


def b_nu(lam_um, temp):
    """Planck por unidad de frecuencia, en unidades arbitrarias (λ en µm).
    Acepta arreglos de temperaturas: b_nu(lam[None, :], T[:, None])."""
    lam = np.asarray(lam_um, dtype=float)
    x = HC_K / (lam * np.asarray(temp, dtype=float))
    with np.errstate(over="ignore"):
        return np.where(x > 700, 0.0, 1 / (lam**3 * np.expm1(np.minimum(x, 700))))


def _fit_grid(lam, flux, err, temps, groups=None, ngroups=0):
    """χ² y escala de un cuerpo negro para cada T de la malla (la escala sale
    exacta por mínimos cuadrados, así que solo se busca en T). Con `groups`
    (índice de visita de cada punto) hay una escala por visita."""
    m = b_nu(lam[None, :], np.asarray(temps, dtype=float)[:, None])
    return _fit_shapes(flux, err, m, groups, ngroups)


def _fit_shapes(flux, err, m, groups=None, ngroups=0):
    """Lo mismo para cualquier familia de formas m (n_formas × n_puntos)."""
    w = 1 / err**2
    if groups is None:
        mm = (w * m * m).sum(1)
        fm = (w * flux * m).sum(1)
        s = np.divide(fm, mm, out=np.zeros_like(fm), where=mm > 0)
        chi2 = (w * (flux - s[:, None] * m) ** 2).sum(1)
        chi2[mm <= 0] = np.inf
        return chi2, s
    g = np.zeros((len(flux), ngroups))
    g[np.arange(len(flux)), groups] = 1
    mm = (w * m * m) @ g
    fm = (w * flux * m) @ g
    s = np.divide(fm, mm, out=np.zeros_like(fm), where=mm > 0)
    chi2 = (w * (flux - s[:, groups] * m) ** 2).sum(1)
    chi2[~np.all(mm > 0, axis=1)] = np.inf
    return chi2, s


def _best(lam, flux, err, temps, groups=None, ngroups=0):
    chi2, s = _fit_grid(lam, flux, err, temps, groups, ngroups)
    i = int(np.argmin(chi2))
    return float(chi2[i]), float(temps[i]), s[i]


def _band_mask(lam, which=None):
    """True donde cae alguna firma (todas, o las de `which`)."""
    out = np.zeros(len(lam), dtype=bool)
    for f in FEATURES:
        if which is None or f["id"] in which:
            out |= (lam >= f["lo"]) & (lam <= f["hi"])
    return out


# El recorte de puntos bajos nunca quita más que esta fracción del continuo:
# en una variable, «bajo» puede ser solo «medido en el mínimo de brillo».
MAX_CLIP = 0.35


def fit_planck(lam, flux, err, mask_bands=True, clip=True, use=None, visit=None, t=None):
    """Temperatura de color. `use` limita los puntos candidatos a continuo.
    Con `visit` (visita de cada punto) cada visita tiene su propia escala: los
    seis canales de una visita son simultáneos, así que la forma sale de los
    colores de cada visita aunque el objeto cambie de brillo entre ellas."""
    cont = np.ones(len(lam), dtype=bool) if use is None else use.copy()
    if mask_bands:
        masked = cont & ~_band_mask(lam)
        if masked.sum() >= MIN_POINTS:
            cont = masked
    groups, ng = None, 0
    if visit is not None:
        # Solo visitas con al menos 2 puntos de continuo dicen algo de la forma.
        ids, counts = np.unique(visit[cont], return_counts=True)
        good = set(ids[counts >= 2].tolist())
        cont &= np.isin(visit, list(good))
        if len(good) < 3:
            return None
        order = sorted(good)
        index = {v: i for i, v in enumerate(order)}
        ng = len(order)
    if cont.sum() < MIN_POINTS:
        return None

    def run(c, temps):
        if visit is None:
            return _best(lam[c], flux[c], err[c], temps)
        gi = np.array([index[v] for v in visit[c]])
        return _best(lam[c], flux[c], err[c], temps, gi, ng)

    def model_of(t_, s_):
        if visit is None:
            return s_ * b_nu(lam, t_)
        # Visitas sin continuo: escala interpolada en el tiempo (en log).
        vt = np.array([t[visit == v].mean() if t is not None else v for v in order])
        ls = np.log(np.maximum(s_, 1e-300))
        pt = np.array([t[i] if t is not None else visit[i] for i in range(len(lam))])
        scale = np.where(np.isin(visit, order),
                         np.array([s_[index[v]] if v in index else 0.0 for v in visit]),
                         np.exp(np.interp(pt, vt, ls)))
        return scale * b_nu(lam, t_)

    n0 = int(cont.sum())
    chi2, temp, s = run(cont, TEMPS)
    for _ in range(5 if clip else 0):
        # Lo que cae muy por debajo del continuo es absorción, no continuo.
        keep = cont & (flux > model_of(temp, s) - 2 * err)
        if keep.sum() < max(MIN_POINTS, (1 - MAX_CLIP) * n0) or keep.sum() == cont.sum():
            break
        if visit is not None and len(set(visit[keep].tolist())) < ng:
            break
        cont = keep
        chi2, temp, s = run(cont, TEMPS)
    fine = np.arange(max(100.0, temp - 40), temp + 41, 1.0)
    chi2s = np.array([run(cont, np.array([x]))[0] for x in fine]) if visit is not None else \
        _fit_grid(lam[cont], flux[cont], err[cont], fine)[0]
    i = int(np.argmin(chi2s))
    chi2, temp, s = run(cont, np.array([fine[i]]))
    dof = max(1, int(cont.sum()) - 1 - (ng if visit is not None else 1))
    red = chi2 / dof
    # Error de T: donde χ² sube 1 (escalado por χ² reducido si el ajuste es
    # peor de lo que dicen los errores). Si se sale de la malla fina, se
    # busca en la gruesa.
    lim = chi2 + max(1.0, red)
    ok = fine[chi2s <= lim]
    if ok.min() <= fine[0] or ok.max() >= fine[-1]:
        c2 = np.array([run(cont, np.array([x]))[0] for x in TEMPS]) if visit is not None else \
            _fit_grid(lam[cont], flux[cont], err[cont], TEMPS)[0]
        ok = TEMPS[c2 <= lim]
        if len(ok) == 0:
            ok = np.array([temp])
    t_err = max(1.0, float(ok.max() - ok.min()) / 2)
    scale = float(np.median(s)) if visit is not None else float(s)
    return {"T": temp, "T_err": t_err, "scale": scale, "chi2": chi2, "red": red, "cont": cont,
            "model": model_of(temp, s), "per_visit": visit is not None}


def variability(lam, flux, err, t, min_days=1.0):
    """¿Cambió el brillo? Sin ningún modelo: pares de medidas casi en la misma
    λ (a menos de un cuarto de elemento de resolución) tomadas con días de
    diferencia deberían coincidir dentro de sus errores. Se usa la mediana
    de |Δf|/σ, que en ruido puro vale 0.674, para que los bordes de banda no
    cuenten. Devuelve {pares, razon} (razon ≈ 1 si no varía) o None."""
    o = np.argsort(lam)
    lam, flux, err, t = lam[o], flux[o], err[o], t[o]
    zs = []
    for i in range(len(lam)):
        tol = 0.25 * lam[i] / resolution(lam[i])
        j = i + 1
        while j < len(lam) and lam[j] - lam[i] < tol:
            if abs(t[j] - t[i]) > min_days:
                zs.append(abs(flux[j] - flux[i]) / np.hypot(err[i], err[j]))
            j += 1
    if len(zs) < 8:
        return None
    return {"pares": len(zs), "razon": round(float(np.median(zs) / 0.674), 2)}


VARIABLE_RATIO = 2.5  # razon por encima de esto: el objeto cambió de brillo


def fit_visit_temps(lam, flux, err, visit, t, mask_bands=True, window=20.0):
    """Para objetos variables: una temperatura y una escala por visita (los
    seis canales de una visita son simultáneos), suavizadas en el tiempo con
    la mediana de las visitas a menos de `window` días. Así el continuo sigue
    al objeto cuando cambia de color con la fase, como una Mira."""
    cont = ~_band_mask(lam) if mask_bands else np.ones(len(lam), dtype=bool)
    ids, counts = np.unique(visit[cont], return_counts=True)
    good = ids[counts >= 3]
    if len(good) < 3:
        return None
    cont &= np.isin(visit, good)
    index = {v: i for i, v in enumerate(good.tolist())}
    gi = np.array([index[v] for v in visit[cont]])
    g = np.zeros((int(cont.sum()), len(good)))
    g[np.arange(len(gi)), gi] = 1
    w = 1 / err[cont] ** 2
    f = flux[cont]
    m = b_nu(lam[cont][None, :], TEMPS[:, None])
    mm = (w * m * m) @ g
    fm = (w * f * m) @ g
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2 = (w * f * f) @ g - np.where(mm > 0, fm * fm / mm, 0.0)
    chi2[mm <= 0] = np.inf
    t_raw = TEMPS[np.argmin(chi2, axis=0)]
    vt = np.array([t[visit == v].mean() for v in good])
    t_sm = np.array([np.median(t_raw[np.abs(vt - x) <= window]) for x in vt])

    def model_for(idx):
        tv = np.interp(t[idx], vt, t_sm)
        out = np.empty(len(idx))
        for k, i in enumerate(idx):
            out[k] = b_nu(lam[i], tv[k])
        return out, tv

    shape_all, temp_all = model_for(np.arange(len(lam)))
    # Escala de cada visita con su T suavizada; donde no hay, interpolada.
    sc = np.zeros(len(good))
    for v, i in index.items():
        sel = cont & (visit == v)
        ww = 1 / err[sel] ** 2
        den = np.sum(ww * shape_all[sel] ** 2)
        sc[i] = np.sum(ww * flux[sel] * shape_all[sel]) / den if den > 0 else 0.0
    ls = np.log(np.maximum(sc, 1e-300))
    scale = np.where(np.isin(visit, good), [sc[index[v]] if v in index else 0.0 for v in visit],
                     np.exp(np.interp(t, vt, ls)))
    model = scale * shape_all
    chi2_tot = float(np.sum(w * (f - model[cont]) ** 2))
    red = chi2_tot / max(1, int(cont.sum()) - 2 * len(good))
    lo, hi = np.percentile(t_sm, [16, 84])
    T = float(np.median(t_sm))
    return {"T": T, "T_err": max(1.0, float(hi - lo) / 2), "scale": float(np.median(sc)), "chi2": chi2_tot,
            "red": red, "cont": cont, "model": model, "per_visit": True, "per_visit_T": True,
            "T_range": [float(t_sm.min()), float(t_sm.max())]}


def fit_continuum(lam, flux, err, visit=None, t=None, mask_bands=True, clip=True, use=None, variable=None):
    """Un cuerpo negro con una sola escala. Si el objeto cambió de brillo
    (`variable`, de `variability`) y una escala por visita mejora mucho el
    ajuste, se usa esa. Sin la prueba de variabilidad, las escalas libres
    absorberían también lo que el espectro tiene de no-cuerpo-negro."""
    g = fit_planck(lam, flux, err, mask_bands, clip, use)
    if g is None or visit is None or not variable or g["red"] <= 3:
        return g
    best = g
    pv = fit_planck(lam, flux, err, mask_bands, clip, use, visit=visit, t=t)
    if pv is not None and pv["red"] < 0.5 * best["red"]:
        best = pv
    if use is None:
        vt = fit_visit_temps(lam, flux, err, visit, t, mask_bands)
        # Una variable cambia de color con el brillo: si la T por visita ajusta
        # al menos igual, es el modelo físicamente correcto.
        if vt is not None and vt["red"] <= best["red"]:
            best = vt
    return best


def fit_star_disk(lam, flux, err, t_star, visit=None, mask_bands=True):
    """Estrella (cuerpo negro a la T medida en < 2.3 µm) más disco de polvo
    tibio (otro cuerpo negro, 300-1500 K). Se busca en una malla de T del
    disco y de su peso relativo a 2.2 µm; la escala va por visita si se da
    `visit`."""
    cont = ~_band_mask(lam) if mask_bands else np.ones(len(lam), dtype=bool)
    groups, ng = None, 0
    if visit is not None:
        ids, counts = np.unique(visit[cont], return_counts=True)
        good = ids[counts >= 2]
        cont &= np.isin(visit, good)
        if len(good) >= 3:
            index = {v: i for i, v in enumerate(good.tolist())}
            groups, ng = np.array([index[v] for v in visit[cont]]), len(good)
    if cont.sum() < MIN_POINTS:
        return None
    star = b_nu(lam, t_star) / b_nu(2.2, t_star)
    tds = np.arange(300.0, 1501.0, 50.0)
    ks = np.geomspace(0.01, 20, 40)
    disk = b_nu(lam[None, :], tds[:, None]) / b_nu(2.2, tds)[:, None]
    shapes = (star[None, None, :] + ks[None, :, None] * disk[:, None, :]).reshape(-1, len(lam))
    chi2, s = _fit_shapes(flux[cont], err[cont], shapes[:, cont], groups, ng)
    i = int(np.argmin(chi2))
    td, k = tds[i // len(ks)], ks[i % len(ks)]
    if groups is None:
        scale = np.full(len(lam), float(s[i]))
    else:
        per = dict(zip(good.tolist(), s[i]))
        med = float(np.median(s[i]))
        scale = np.array([per.get(v, med) for v in visit])
    red = float(chi2[i]) / max(1, int(cont.sum()) - 3 - max(ng, 1))
    return {"T_estrella_K": float(t_star), "T_disco_K": float(td), "peso_disco_2_2um": round(float(k), 3),
            "chi2_reducido": round(red, 2), "model": scale * shapes[i], "red": red}


def fit_solar_system(lam, flux, err, mask_bands=True):
    """Luz del Sol reflejada (cuerpo negro de 5800 K por un albedo gris) más
    emisión térmica propia (~150-700 K a 1-3 UA del Sol)."""
    cont = ~_band_mask(lam) if mask_bands else np.ones(len(lam), dtype=bool)
    if cont.sum() < MIN_POINTS:
        cont = np.ones(len(lam), dtype=bool)
    w = 1 / err[cont] ** 2
    sun = b_nu(lam, T_SUN)
    best = None
    for tt in np.arange(100.0, 701.0, 5.0):
        th = b_nu(lam, tt)
        a = np.column_stack([sun[cont], th[cont]])
        ata = a.T @ (a * w[:, None])
        if np.linalg.cond(ata) > 1e14:
            continue
        coef = np.linalg.solve(ata, a.T @ (w * flux[cont]))
        if coef[0] < 0 or coef[1] < 0:
            # Sin una de las dos componentes.
            coef = np.maximum(coef, 0)
        chi2 = float(np.sum(w * (flux[cont] - a @ coef) ** 2))
        if best is None or chi2 < best[0]:
            cov = np.linalg.inv(ata)
            best = (chi2, tt, coef, cov)
    if best is None:
        return None
    chi2, tt, (ar, at), cov = best
    reflected, thermal = ar * sun, at * b_nu(lam, tt)
    model = reflected + thermal
    i46 = (np.abs(lam - 4.6) < 0.2)
    frac46 = float(np.sum(thermal[i46]) / np.sum(model[i46])) if i46.any() and np.sum(model[i46]) > 0 else None
    red = chi2 / max(1, int(cont.sum()) - 3)
    z_th = float(at / np.sqrt(cov[1, 1] * max(1.0, red))) if cov[1, 1] > 0 else 0.0
    return {
        "T_termica_K": float(tt), "chi2_reducido": round(red, 2),
        "fraccion_termica_4_6um": None if frac46 is None else round(frac46, 3),
        "z_termica": round(z_th, 1), "model": model,
        "nota": _msg("ss.size",
                     "Con la distancia al Sol y a la Tierra (efemérides), el exceso térmico a 4-5 µm "
                     "da el tamaño y el albedo.",
                     "With the distances to the Sun and the Earth (ephemerides), the thermal excess "
                     "at 4-5 µm gives the size and the albedo."),
    }


def local_continuum(lam, flux, err, cont, lo, hi, exclude):
    """Continuo local de [lo, hi]: el continuo global (`cont`) corregido por
    una recta ajustada en dos ventanas a cada lado. Con el continuo global
    plano (unos) es la recta de siempre; con el cuerpo negro, la recta solo
    corrige lo que el cuerpo negro no sigue. Devuelve el continuo y su error
    relativo en cada punto, o None si faltan puntos en alguna ventana."""
    usable = (cont > 3 * err) & ~exclude
    width = hi - lo
    for k in (1, 2, 3):
        win = k * max(0.06, 0.6 * width)
        left = (lam >= lo - win) & (lam < lo) & usable
        right = (lam > hi) & (lam <= hi + win) & usable
        if left.sum() >= 1 and right.sum() >= 1 and left.sum() + right.sum() >= 3:
            break
    else:
        return None
    sel = left | right
    x0 = (lo + hi) / 2
    x = lam[sel] - x0
    r = flux[sel] / cont[sel]
    w = (cont[sel] / err[sel]) ** 2
    a = np.column_stack([np.ones_like(x), x])
    ata = a.T @ (a * w[:, None])
    if np.linalg.cond(ata) > 1e12:
        return None
    cov = np.linalg.inv(ata)
    coef = cov @ (a.T @ (w * r))
    red = float(np.sum(w * (r - a @ coef) ** 2)) / max(1, int(sel.sum()) - 2)
    cov = cov * max(1.0, red)
    xx = lam - x0
    line = coef[0] + coef[1] * xx
    var = cov[0, 0] + 2 * xx * cov[0, 1] + xx * xx * cov[1, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(line > 0, np.sqrt(np.maximum(var, 0)) / np.abs(line), np.inf)
    return cont * line, rel


def feature_depth(lam, flux, err, cont, lo, hi, cont_rel=None):
    """Profundidad d = 1 - <F/F_cont> con pesos de varianza inversa, su error
    y su significancia. d > 0 es absorción, d < 0 emisión."""
    sel = (lam >= lo) & (lam <= hi) & (cont > 3 * err)
    if sel.sum() < 2:
        return None
    w = (cont[sel] / err[sel]) ** 2
    d = 1 - np.sum(w * flux[sel] / cont[sel]) / w.sum()
    sigma = 1 / np.sqrt(w.sum())
    if cont_rel is not None:
        sigma = float(np.hypot(sigma, np.sum(w * cont_rel[sel]) / w.sum()))
    return float(d), float(sigma), float(d / sigma), int(sel.sum())


def _signed(kind, z):
    """Significancia con el signo que la firma debe tener."""
    return z if kind == "abs" else -z if kind == "emi" else abs(z)


def _state(f, z):
    s = _signed(f["kind"], z)
    if s >= Z_DETECT:
        return "compatible" if f["line"] else "detectada"
    if s >= Z_HINT:
        return "indicio"
    if s <= -Z_DETECT and f["kind"] != "either":
        return "opuesta"
    return "no"


def _range(lam, f):
    return (lam >= f["lo"]) & (lam <= f["hi"])


def measure_features(lam, flux, err, continuum, inflate=1.0):
    """Dos pasadas: primero las bandas contra el continuo global; luego las
    que usan continuo local, con ventanas que esquivan las bandas detectadas
    (salvo la que contiene a la firma, p. ej. Paα dentro del agua de 1.9 µm)
    y las demás líneas. Una línea sin ventanas limpias no se mide: junto al
    borde de una banda ancha, cualquier «bulto» sería el borde."""
    res = {}
    for f in FEATURES:
        if f["continuum"] == "planck" and continuum is not None:
            r = feature_depth(lam, flux, err, continuum, f["lo"], f["hi"])
            if r is not None:
                res[f["id"]] = (r, "planck")
    strong = {k for k, (r, _) in res.items() if _signed(BY_ID[k]["kind"], r[2]) >= Z_DETECT}
    for f in FEATURES:
        if f["continuum"] != "local":
            continue
        avoid = np.zeros(len(lam), dtype=bool)
        for g in FEATURES:
            if g["id"] == f["id"] or (g["lo"] <= f["lo"] and f["hi"] <= g["hi"]):
                continue
            if g["id"] in strong or g["kind"] != "abs":
                avoid |= _range(lam, g)
        base = continuum if continuum is not None else np.ones(len(lam))
        lc = local_continuum(lam, flux, err, base, f["lo"], f["hi"], avoid)
        r = feature_depth(lam, flux, err, lc[0], f["lo"], f["hi"], lc[1]) if lc is not None else None
        if r is not None:
            res[f["id"]] = (r, "local")
        elif not f["line"] and continuum is not None:
            r = feature_depth(lam, flux, err, continuum, f["lo"], f["hi"])
            if r is not None:
                res[f["id"]] = (r, "planck")
    out = []
    for f in FEATURES:
        if f["id"] not in res:
            continue
        (d, sigma, z, n), method = res[f["id"]]
        # Si el continuo no ajusta tan bien como dicen los errores (χ² > 1),
        # tampoco las profundidades medidas contra él.
        sigma *= inflate
        z = d / sigma
        out.append({
            "id": f["id"], "especie": f["species"], "etiqueta": f["label"], "lo": f["lo"], "hi": f["hi"],
            "centro": f["center"], "tipo": f["kind"], "linea": f["line"], "metodo": method,
            "d": round(d, 4), "sigma": round(sigma, 4), "z": round(z, 2), "n": n, "estado": _state(f, z),
            "observado": "absorción" if d > 0 else "emisión",
        })
    return out


def ir_excess(lam, flux, err, visit=None, t=None, variable=False):
    """Luz a 3.8-5 µm por encima del cuerpo negro ajustado a < 2.3 µm. Solo
    tiene sentido en estrellas (T > 2500 K); en enanas marrones el «exceso» es
    la ventana de 4 µm de su propia atmósfera."""
    short = lam < 2.3
    long_ = (lam >= 3.8) & (lam <= 5.0) & ~_band_mask(lam)
    if short.sum() < MIN_POINTS or long_.sum() < 3:
        return None
    # La estrella tiene que verse en el corto: extrapolar ruido no vale.
    if np.mean(flux[short] > 3 * err[short]) < 0.5:
        return None
    fit = fit_continuum(lam, flux, err, visit, t, use=short, variable=variable)
    if fit is None or fit["T"] < 2500:
        return None
    m = fit["model"][long_]
    if not np.all(m > 0):
        return None
    w = (m / err[long_]) ** 2
    r = float(np.sum(w * flux[long_] / m) / w.sum())
    sigma = 1 / np.sqrt(w.sum())
    # Lo que la incertidumbre de T mueve la extrapolación.
    hot = b_nu(lam[long_], fit["T"] + fit["T_err"]) / b_nu(lam[long_], fit["T"])
    cold = b_nu(lam[long_], max(100.0, fit["T"] - fit["T_err"])) / b_nu(lam[long_], fit["T"])
    sigma = float(np.hypot(sigma, np.median(np.abs(cold - hot)) / 2))
    return {"T_corto_K": fit["T"], "cociente": round(r, 3), "sigma": round(sigma, 3),
            "z": round((r - 1) / sigma, 1)}


def _g(s):
    """De significancia a puntaje 0-1: z ≤ 1 no cuenta, z ≥ 5 cuenta completo."""
    return float(np.clip((s - 1) / 4, 0, 1))


def _t_factor(T, rng):
    """1 dentro del rango de T; baja a 0 en un 15 % más allá de cada borde
    (la T de color es aproximada)."""
    if rng is None or T is None:
        return 1.0
    lo, hi = rng
    if lo <= T <= hi:
        return 1.0
    edge = lo if T < lo else hi
    return float(max(0.0, 1 - abs(T - edge) / (0.15 * edge)))


def signals(firmas, extra=None):
    """{id: significancia con signo}, con id:abs e id:emi para las ambiguas."""
    out = {}
    for f in firmas:
        out[f["id"]] = _signed(f["tipo"], f["z"])
        if f["tipo"] == "either":
            out[f["id"] + ":abs"] = f["z"]
            out[f["id"] + ":emi"] = -f["z"]
    out.update(extra or {})
    return out


def classify(T, sig, solar_system=False):
    """Lista ordenada de familias plausibles con su puntaje (0-1)."""
    out = []
    for r in RULES:
        if bool(r.get("solar_system")) != solar_system:
            continue
        tf = _t_factor(T, r.get("T"))
        if tf == 0:
            continue
        want = list(r.get("want", []))
        measured = [(f, w) for f, w in want if f in sig]
        if want:
            if not measured:
                continue
            score = sum(w * _g(sig[f]) for f, w in measured) / sum(w for _, w in measured)
            # Si faltó medir parte de lo que la regla pide, cuenta menos.
            score *= np.sqrt(sum(w for _, w in measured) / sum(w for _, w in want))
        else:
            score = r.get("base", 0.5)
        bonus = [_g(sig[b]) for b in r.get("bonus", []) if b in sig]
        score = min(1.0, score + 0.3 * max(bonus, default=0.0))
        avoid = [_g(sig[a]) for a in r.get("avoid", []) if a in sig]
        score *= (1 - max(avoid, default=0.0)) * tf
        if score < 0.05:
            continue
        out.append({
            "id": r["id"], "nombre": r["name"], "desc": r["desc"], "puntaje": round(float(score), 2),
            "por": [f for f, _ in measured if _g(sig[f]) > 0] + [b for b in r.get("bonus", []) if b in sig and _g(sig[b]) > 0],
            "contra": [a for a in r.get("avoid", []) if a in sig and _g(sig[a]) > 0],
            "sin_medir": [f for f, _ in want if f not in sig],
        })
    return sorted(out, key=lambda c: -c["puntaje"])


def _prepare(measurements, systematic):
    m = [x for x in measurements if x.get("ok") and x.get("e", 0) > 0 and x.get("f") is not None]
    lam = np.array([x["l"] for x in m], dtype=float)
    flux = np.array([x["f"] for x in m], dtype=float)
    err = np.array([x["e"] for x in m], dtype=float)
    err = np.hypot(err, systematic * np.abs(flux))
    t = np.array([x.get("t", 0.0) for x in m], dtype=float)
    # Visita de cada punto; sin ella, las medidas con el mismo tiempo.
    if m and all("v" in x for x in m):
        visit = np.array([int(x["v"]) for x in m])
    else:
        visit = np.unique(np.round(t, 4), return_inverse=True)[1]
    return m, lam, flux, err, t, visit


def _per_channel(measurements):
    out = {f"canal {c + 1}": {"medidas": 0, "fiables": 0} for c in range(6)}
    for x in measurements:
        k = f"canal {x['c'] + 1}"
        if k in out:
            out[k]["medidas"] += 1
            out[k]["fiables"] += bool(x.get("ok"))
    return out


def analyze(measurements, mask_bands=True, clip=True, systematic=SYSTEMATIC, solar_system=False):
    """measurements: lista de dicts {c, l, f, e, ok, t} (como en el evento select)."""
    por_canal = _per_channel(measurements)
    m, lam, flux, err, t, visit = _prepare(measurements, systematic)
    if len(m) < MIN_POINTS:
        return {"error": _msg("few", "Muy pocas medidas fiables (¿fuente saturada o todavía cargando?).",
                              "Too few reliable measurements (saturated source, or still loading?)."),
                "puntos": len(m), "por_canal": por_canal}
    var = variability(lam, flux, err, t)
    variable = var is not None and var["razon"] > VARIABLE_RATIO
    fit = fit_continuum(lam, flux, err, visit, t, mask_bands, clip, variable=variable)
    if fit is None:
        return {"error": _msg("fit", "No hay puntos suficientes fuera de las bandas para ajustar el continuo.",
                              "Not enough points outside the bands to fit the continuum."),
                "puntos": len(m), "por_canal": por_canal}
    ss = fit_solar_system(lam, flux, err, mask_bands) if solar_system else None
    exceso = None if solar_system else ir_excess(lam, flux, err, visit, t, variable)
    disco = None
    if exceso is not None and exceso["z"] > 5:
        # Con polvo tibio el continuo no es un cuerpo negro: estrella + disco.
        disco = fit_star_disk(lam, flux, err, exceso["T_corto_K"], visit if fit["per_visit"] else None, mask_bands)
        if disco is not None and disco["red"] >= fit["red"]:
            disco = None
    continuum = ss["model"] if ss is not None else disco["model"] if disco is not None else fit["model"]
    red_cont = ss["chi2_reducido"] if ss is not None else disco["red"] if disco is not None else fit["red"]
    firmas = measure_features(lam, flux, err, continuum, np.sqrt(max(1.0, red_cont)))
    T = fit["T"]
    extra = {"very_cold": (700 - T) / max(fit["T_err"], 30.0)} if not solar_system else {}
    if exceso is not None:
        extra["ir_excess"] = exceso["z"]
    if ss is not None:
        extra["thermal"] = ss["z_termica"]
    sig = signals(firmas, extra)
    clases = classify(T, sig, solar_system)

    avisos, notas = [], []
    canales_ok = sum(1 for v in por_canal.values() if v["fiables"] > 0)
    if canales_ok < 3 or float(lam.max() - lam.min()) < 1.5:
        avisos.append(_msg("range",
                           f"Solo {canales_ok} canal(es) con medidas fiables ({lam.min():.2f}-{lam.max():.2f} µm): "
                           "con un rango tan corto la temperatura no queda determinada.",
                           f"Only {canales_ok} channel(s) with reliable measurements ({lam.min():.2f}-{lam.max():.2f} µm): "
                           "with such a short range the temperature is not constrained."))
    if any(v["medidas"] and not v["fiables"] for v in por_canal.values()):
        avisos.append(_msg("saturated", "Hay canales con medidas pero ninguna fiable: la fuente probablemente satura el detector.",
                           "Some channels have measurements but none reliable: the source probably saturates the detector."))
    counts = [v["medidas"] for v in por_canal.values() if v["medidas"]]
    if len(set(counts)) > 1 and min(counts) < 0.5 * max(counts):
        avisos.append(_msg("loading", "Algunos canales tienen muchas menos medidas que otros: puede que aún estuvieran cargando.",
                           "Some channels have far fewer measurements than others: they may still be loading."))
    if fit["cont"].sum() < 20:
        avisos.append(_msg("fewcont", f"El continuo se ajustó con solo {int(fit['cont'].sum())} puntos.",
                           f"The continuum was fitted with only {int(fit['cont'].sum())} points."))
    if variable:
        notas.append(_msg("varies", f"Medidas a la misma λ en distintas visitas difieren {var['razon']:.1f} veces más de lo "
                          "que explican sus errores: el objeto cambia de brillo.",
                          f"Measurements at the same λ in different visits differ {var['razon']:.1f} times more than their "
                          "errors explain: the object changes in brightness."))
    if fit["per_visit"]:
        what_es, what_en = ("una temperatura y una escala", "one temperature and one scale") if fit.get("per_visit_T") \
            else ("una escala", "one scale")
        notas.append(_msg("pervisit", f"El continuo se ajustó con {what_es} por visita: los seis canales de cada visita "
                          "se miden a la vez, así que cada visita es un espectro instantáneo de baja resolución.",
                          f"The continuum was fitted with {what_en} per visit: the six channels of a visit are measured "
                          "at the same time, so each visit is an instantaneous low-resolution spectrum."))
    if red_cont > 5:
        avisos.append(_msg("chi2", f"El continuo ajusta mal (χ² reducido {red_cont:.1f}): objeto variable, saturado o no parecido "
                           "a un cuerpo negro. Las significancias ya se corrigieron por esto.",
                           f"The continuum fits poorly (reduced χ² {red_cont:.1f}): variable or saturated object, or not like a "
                           "black body. The significances are already corrected for this."))

    span = float(t.max() - t.min()) if t.any() else 0.0
    if span > SEASON_GAP:
        notas.append(_msg("seasons", f"Este espectro junta medidas de {span:.0f} días. En un objeto variable la forma mezcla química "
                          "con tiempo: compara temporada por temporada.",
                          f"This spectrum combines measurements over {span:.0f} days. In a variable object its shape mixes chemistry "
                          "with time: compare season by season."))
    elif span > 0:
        notas.append(_msg("nonsim", f"El espectro no es simultáneo: cada longitud de onda se midió en otra visita ({span:.0f} días en total).",
                          f"The spectrum is not simultaneous: each wavelength was measured in a different visit ({span:.0f} days in all)."))
    if any(f["linea"] and f["estado"] == "compatible" for f in firmas):
        notas.append(_msg("lines", "SPHEREx no resuelve líneas finas (λ/Δλ ≈ 35-130): salen como bultos, por eso dicen «compatible con».",
                          "SPHEREx does not resolve narrow lines (λ/Δλ ≈ 35-130): they show up as bumps, hence «compatible with»."))
    if clases and clases[0]["id"].startswith("brown_dwarf") or T < 2000:
        notas.append(_msg("tcolor", "En enanas marrones la temperatura de color no es la efectiva: la absorción molecular deforma el "
                          "cuerpo negro. Para clasificar pesan más las bandas que T.",
                          "In brown dwarfs the color temperature is not the effective one: molecular absorption distorts the "
                          "black body. The bands weigh more than T in the classification."))

    grid = np.linspace(0.75, 5.0, 86)
    if ss is not None or disco is not None or fit["per_visit"]:
        # Estos modelos se evalúan en los puntos medidos (con su escala de
        # cada visita); para dibujarlos se suaviza la curva sobre la malla.
        order = np.argsort(lam)
        curve = _smooth_curve(lam[order], continuum[order], grid)
    else:
        curve = fit["scale"] * b_nu(grid, T)
    out = {
        "confiable": not avisos,
        "avisos": avisos,
        "notas": notas,
        "T_color_K": T,
        "T_err_K": round(fit["T_err"], 0),
        # Con T por visita (objetos variables): de cuánto a cuánto cambió.
        "T_rango_K": fit.get("T_range"),
        # Pico de B_lambda (ley de Wien). En F_nu el pico está en 5100/T µm.
        "pico_wien_um": round(2897.77 / T, 2),
        "puntos": len(m),
        "puntos_continuo": int(fit["cont"].sum()),
        "chi2_reducido": round(float(red_cont), 2),
        "escala": fit["scale"],
        "escala_por_visita": fit["per_visit"],
        "variabilidad": var,
        # Flujo del continuo y error típico de las medidas cerca de cada λ:
        # para comparar el brillo entre temporadas donde sí se mide algo.
        "ref": _reference(lam, err, fit["scale"], T, fit["T_err"]),
        "mjd": [round(float(t.min()), 3), round(float(t.max()), 3)] if t.any() else None,
        "firmas": firmas,
        "depths": {f["id"]: f["d"] for f in firmas},
        "sigma": {f["id"]: f["sigma"] for f in firmas},
        "z": {f["id"]: f["z"] for f in firmas},
        "exceso_ir": exceso,
        "clasificacion": clases,
        "continuo": [[round(float(a), 3), float(b)] for a, b in zip(grid, curve)],
        "por_canal": por_canal,
    }
    ok = continuum > 3 * err
    o = np.argsort(lam[ok])
    # Interno (no sale en el JSON): para comparar temporadas en las mismas λ.
    out["_ratio"] = (lam[ok][o], (flux[ok] / continuum[ok])[o], (err[ok] / continuum[ok])[o])
    if ss is not None:
        out["sistema_solar"] = {k: v for k, v in ss.items() if k != "model"}
    if disco is not None:
        out["estrella_disco"] = {k: v for k, v in disco.items() if k not in ("model", "red")}
    return out


def _smooth_curve(x, y, grid, width=0.08):
    """Mediana móvil de (x, y) evaluada en la malla; donde no hay puntos,
    interpolación."""
    out = np.empty(len(grid))
    for i, g in enumerate(grid):
        near = np.abs(x - g) < width
        out[i] = np.median(y[near]) if near.any() else np.nan
    ok = ~np.isnan(out)
    return np.interp(grid, grid[ok], out[ok]) if ok.any() else np.interp(grid, x, y)


def split_seasons(measurements, gap=SEASON_GAP):
    """{temporada: medidas}. Usa `s` si el motor lo puso; si no, corta donde
    hay más de `gap` días sin medidas."""
    if measurements and all("s" in x for x in measurements):
        out = {}
        for x in measurements:
            out.setdefault(int(x["s"]), []).append(x)
        return dict(sorted(out.items()))
    xs = sorted(measurements, key=lambda x: x.get("t", 0.0))
    out, season, last = {}, 0, None
    for x in xs:
        t = x.get("t", 0.0)
        if last is not None and t - last > gap:
            season += 1
        out.setdefault(season, []).append(x)
        last = t
    return out


REF_LAMBDAS = (1.2, 2.2, 4.6)
# Diferencias de profundidad entre temporadas por debajo de esto no cuentan:
# cada temporada muestrea la banda en otras longitudes de onda, y una banda
# no es una caja.
DEPTH_SYS = 0.025
T_SYS = 0.01  # fracción de T


def _reference(lam, err, scale, T, T_err):
    """[flujo del continuo, error típico de una medida cerca, error relativo
    del continuo por la incertidumbre de T] en cada λ de referencia."""
    out = {}
    for x in REF_LAMBDAS:
        near = np.abs(lam - x) < 0.3
        if near.any():
            f = float(scale * b_nu(x, T))
            if f <= 0:
                continue
            rel_t = abs(float(b_nu(x, T + T_err) - b_nu(x, max(100.0, T - T_err)))) / (2 * float(b_nu(x, T)))
            out[f"{x}um"] = [f, float(np.median(err[near])), rel_t, int(near.sum())]
    return out


def _dmag(ra, rb, key):
    a, b = ra.get("ref", {}).get(key), rb.get("ref", {}).get(key)
    if not a or not b or a[0] <= 3 * a[1] or b[0] <= 3 * b[1]:
        return None
    dm = -2.5 * np.log10(b[0] / a[0])
    # Error de la media de los puntos cercanos más lo que mueve la T.
    e = 1.0857 * np.sqrt((a[1] / a[0]) ** 2 / a[3] + (b[1] / b[0]) ** 2 / b[3] + a[2] ** 2 + b[2] ** 2)
    return {"dmag": round(float(dm), 3), "err": round(float(max(e, 0.01)), 3)}


def _dmag_data(ra, ms_a, ms_b, key, lam_ref):
    """Cambio de brillo cerca de lam_ref medido en los datos: el modelo de la
    temporada a solo corrige que cada temporada midió en otras λ."""
    vals = []
    for ms in (ms_a, ms_b):
        _, lam, flux, err, _, _ = _prepare(ms, SYSTEMATIC)
        model = ra["escala"] * b_nu(lam, ra["T_color_K"])
        sel = (np.abs(lam - lam_ref) < 0.3) & (flux > 3 * err) & (model > 0)
        if sel.sum() < 2:
            return None
        y = np.log(flux[sel] / model[sel])
        w = (flux[sel] / err[sel]) ** 2
        mean = float(np.sum(w * y) / w.sum())
        # Error: el formal o la dispersión de los puntos, lo que sea mayor.
        spread = float(np.sqrt(np.sum(w * (y - mean) ** 2) / w.sum() / max(1, sel.sum() - 1)))
        vals.append((mean, max(1 / np.sqrt(w.sum()), spread)))
    (ya, ea), (yb, eb) = vals
    return {"dmag": round(-1.0857 * (yb - ya), 3), "err": round(max(0.01, 1.0857 * float(np.hypot(ea, eb))), 3)}


def _ratio(r, ms):
    """λ, F/F_continuo y su error de las medidas de una temporada, contra el
    continuo de cada punto (con su escala y T de visita si las hubo)."""
    lam, q, e = r["_ratio"]
    # Igual que en las profundidades: si el continuo ajusta peor de lo que
    # dicen los errores, el cociente tampoco es tan preciso.
    return lam, q, e * np.sqrt(max(1.0, r["chi2_reducido"]))


def _depth_changes(ra, rb, ms_a, ms_b):
    """Cambio de profundidad de cada firma comparando en las mismas λ: el
    cociente F/continuo de la temporada a se interpola en las λ que midió la
    b. Así no cuenta como cambio que cada temporada tocara otra parte de la
    banda."""
    la, qa, ea = _ratio(ra, ms_a)
    lb, qb, eb = _ratio(rb, ms_b)
    out = []
    for f in FEATURES:
        if f["id"] not in ra["depths"] or f["id"] not in rb["depths"]:
            continue
        ia = (la >= f["lo"]) & (la <= f["hi"])
        ib = (lb >= f["lo"]) & (lb <= f["hi"])
        if ia.sum() < 2 or ib.sum() < 2:
            continue
        x = lb[ib]
        inside = (x >= la[ia].min()) & (x <= la[ia].max())
        if inside.sum() < 2:
            continue
        qa_at = np.interp(x[inside], la[ia], qa[ia])
        w = 1 / (eb[ib][inside] ** 2 + np.median(ea[ia]) ** 2)
        dd = float(np.sum(w * (qa_at - qb[ib][inside])) / w.sum())  # > 0: más profunda en b
        s = float(np.sqrt(1 / w.sum() + 2 * DEPTH_SYS**2))
        if abs(dd) > Z_CHANGE * s:
            out.append({"id": f["id"], "d_a": ra["depths"][f["id"]], "d_b": rb["depths"][f["id"]], "dd": round(dd, 4),
                        "sigma": round(s, 4), "n_sigma": round(abs(dd) / s, 1)})
    return out


def compare_epochs(ra, rb, ms_a=None, ms_b=None):
    """Qué cambió de la temporada a a la b: temperatura, brillo y firmas.
    Con las medidas de cada temporada, el cambio de brillo sale de los datos;
    sin ellas, de los modelos de continuo."""
    dT = rb["T_color_K"] - ra["T_color_K"]
    sT = float(np.hypot(np.hypot(ra["T_err_K"], rb["T_err_K"]),
                        T_SYS * (ra["T_color_K"] + rb["T_color_K"]) / 2))
    cambios = []
    for k in ([] if ms_a is not None and ms_b is not None else ra["depths"]):
        if k not in rb["depths"]:
            continue
        dd = rb["depths"][k] - ra["depths"][k]
        s = float(np.sqrt(ra["sigma"][k] ** 2 + rb["sigma"][k] ** 2 + 2 * DEPTH_SYS**2))
        if abs(dd) > Z_CHANGE * s:
            cambios.append({"id": k, "d_a": ra["depths"][k], "d_b": rb["depths"][k], "dd": round(dd, 4),
                            "sigma": round(s, 4), "n_sigma": round(abs(dd) / s, 1),
                            "dz": round(rb["z"][k] - ra["z"][k], 2)})
    if ms_a is not None and ms_b is not None:
        cambios = _depth_changes(ra, rb, ms_a, ms_b)
        dmag = {f"{x}um": _dmag_data(ra, ms_a, ms_b, f"{x}um", x) for x in REF_LAMBDAS}
    else:
        dmag = {k: _dmag(ra, rb, k) for k in (f"{x}um" for x in REF_LAMBDAS)}
    dmag = {k: v for k, v in dmag.items() if v is not None}
    top = lambda r: r["clasificacion"][0]["id"] if r.get("clasificacion") else None
    return {
        "dT_K": dT, "dT_err_K": round(sT, 0), "T_cambia": abs(dT) > Z_CHANGE * sT,
        # Cambio de brillo del continuo (positivo = más débil).
        "dmag": dmag,
        "brillo_cambia": any(abs(v["dmag"]) > Z_CHANGE * v["err"] and abs(v["dmag"]) > 0.05 for v in dmag.values()),
        "cambios": sorted(cambios, key=lambda c: -c["n_sigma"]),
        "clase_a": top(ra), "clase_b": top(rb),
    }


SEASON_KEYS = ("T_color_K", "T_err_K", "chi2_reducido", "puntos", "mjd", "escala", "escala_por_visita", "variabilidad", "ref",
               "depths", "sigma", "z", "confiable", "error")


def analyze_seasons(measurements, solar_system=False, **kw):
    """El análisis de todo junto, más uno por temporada y lo que cambió entre
    temporadas consecutivas."""
    full = analyze(measurements, solar_system=solar_system, **kw)
    seasons = split_seasons(measurements)
    per = []
    for s, ms in seasons.items():
        r = analyze(ms, solar_system=solar_system, **kw)
        per.append((s, r))
    full["temporadas"] = [
        dict({k: r[k] for k in SEASON_KEYS if k in r}, temporada=s,
             clase=r["clasificacion"][0]["id"] if r.get("clasificacion") else None)
        for s, r in per
    ]
    ok = [(s, r) for s, r in per if "error" not in r]
    full["cambios"] = [dict(compare_epochs(ra, rb, seasons[sa], seasons[sb]), temporadas=[sa, sb])
                       for (sa, ra), (sb, rb) in zip(ok, ok[1:])]
    # En un objeto que no es cuerpo negro (una enana marrón) la T de color se
    # mueve con las λ que tocó medir en cada temporada. Un cambio de T solo
    # cuenta si el brillo también cambió.
    var = full.get("variabilidad")
    varies = var is not None and var["razon"] > VARIABLE_RATIO
    for c in full["cambios"]:
        c["T_cambia"] = c["T_cambia"] and (varies or c["brillo_cambia"])
    notas = full.setdefault("notas", [])
    if any(c["T_cambia"] or c["brillo_cambia"] or c["cambios"] for c in full["cambios"]):
        notas.append(_msg(
            "variable", "El espectro cambia entre temporadas: el objeto es variable, así que el espectro combinado "
            "mezcla estados distintos.",
            "The spectrum changes between seasons: the object is variable, so the combined spectrum mixes "
            "different states."))
    elif full["cambios"]:
        # Nada cambió: juntar temporadas es seguro y la nota general sobra.
        full["notas"] = [n for n in notas if n["id"] != "seasons"] + [_msg(
            "stable", f"Sin cambios entre {len(ok)} temporadas: el espectro combinado es fiable.",
            f"No changes across {len(ok)} seasons: the combined spectrum can be trusted.")]
    return full


def to_json(r):
    """El resultado listo para JSON estricto: sin NaN ni infinitos, sin tipos
    de numpy y sin las claves internas."""
    if isinstance(r, dict):
        return {k: to_json(v) for k, v in r.items() if k != "model" and not k.startswith("_")}
    if isinstance(r, (list, tuple)):
        return [to_json(v) for v in r]
    if isinstance(r, (bool, np.bool_)):
        return bool(r)
    if isinstance(r, (int, np.integer)):
        return int(r)
    if isinstance(r, (float, np.floating)):
        return float(r) if np.isfinite(r) else None
    return r


def describe(r, lang="es"):
    """Resumen de texto del análisis, para la terminal."""
    if "error" in r:
        return r["error"][lang]
    lines = [f"T de color {r['T_color_K']:.0f} ± {r['T_err_K']:.0f} K · χ²red {r['chi2_reducido']}"
             if lang == "es" else
             f"Color T {r['T_color_K']:.0f} ± {r['T_err_K']:.0f} K · red. χ² {r['chi2_reducido']}"]
    for c in r["clasificacion"][:3]:
        lines.append(f"  {c['puntaje']:.2f}  {c['nombre'][lang]}  ({', '.join(c['por']) or '-'})")
    for f in r["firmas"]:
        if f["estado"] in ("detectada", "compatible", "indicio", "opuesta"):
            lines.append(f"  {f['etiqueta']:<6} {f['lo']:.2f}-{f['hi']:.2f} µm  d={f['d']:+.3f} ± {f['sigma']:.3f}"
                         f"  z={f['z']:+.1f}  {f['estado']}  [{f['metodo']}]")
    for c in r.get("cambios", []):
        dm = ", ".join(f"Δmag {k}={v['dmag']:+.2f}±{v['err']:.2f}" for k, v in c["dmag"].items())
        lines.append(f"  temporada {c['temporadas'][0] + 1}→{c['temporadas'][1] + 1}: ΔT={c['dT_K']:+.0f} ± "
                     f"{c['dT_err_K']:.0f} K{' (cambia)' if c['T_cambia'] else ''}, {dm}, "
                     f"cambian: {', '.join(x['id'] for x in c['cambios']) or 'ninguna'}")
    for a in r["avisos"] + r.get("notas", []):
        lines.append("  ! " + a[lang])
    return "\n".join(lines)


def main(argv=None):
    import argparse
    import json

    p = argparse.ArgumentParser(prog="python -m spherex.espectro", description=__doc__.split("\n\n")[0])
    p.add_argument("file", help="JSON del evento select (con la lista measurements)")
    p.add_argument("--por-temporada", action="store_true", help="analiza cada temporada y compara")
    p.add_argument("--sistema-solar", action="store_true", help="continuo de luz solar reflejada + térmica")
    p.add_argument("--json", action="store_true", help="salida JSON completa")
    p.add_argument("--lang", default="es", choices=("es", "en"))
    a = p.parse_args(argv)
    with open(a.file, encoding="utf-8") as fh:
        sel = json.load(fh)
    ms = sel["measurements"] if isinstance(sel, dict) else sel
    fn = analyze_seasons if a.por_temporada else analyze
    r = fn(ms, solar_system=a.sistema_solar)
    if a.json:
        r.pop("continuo", None)
        print(json.dumps(to_json(r), indent=2, ensure_ascii=False))
    else:
        print(describe(r, a.lang))


if __name__ == "__main__":
    main()
