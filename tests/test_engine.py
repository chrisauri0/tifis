"""The engine without HTTP: composition modes, references, stretch, retries."""

from __future__ import annotations

import base64
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

from spherex import sky
from spherex.engine import App, OpenRequest, Stretch, ViewState, colorize, compose, reference
from spherex.engine import app as app_module
from spherex.proxy import UpstreamError

DATA = Path(__file__).parent / "data"


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, payload):
        json.dumps(payload, allow_nan=False)  # every event must be valid JSON
        self.events.append((kind, payload))

    def last(self, kind):
        return next((p for k, p in reversed(self.events) if k == kind), None)


def run_until(app, pred, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "timed out"
        app.update(0.05)
        time.sleep(0.005)


def sim_app(view=None):
    rec = Recorder()
    app = App(rec, None)
    if view:
        app.set_view(view)
    t = sky.TARGETS[0].source
    ra, dec = t.position(sky.now_mjd())
    app.open(OpenRequest(ra, dec, 6, "", False))
    run_until(app, lambda: not app.loader.pending)
    app.update(0.05)
    return app, rec


def test_open_rounds_and_clamps():
    app, rec = sim_app()
    f = rec.last("field")
    assert f["fov"] == 6 and f["npix"] == 59 and f["name"] == "Barnard's Star"
    assert f["ra"] * 2000 == round(f["ra"] * 2000)
    app.open(OpenRequest(10.0002, -5, 40, "Somewhere", False))
    f = rec.last("field")
    assert f["fov"] == 12 and f["ra"] == 10.0 and f["name"] == "Somewhere" and f["npix"] == 117


def test_compose_modes():
    app, rec = sim_app(ViewState(band=1, mode="epoch", visit=10, ref=-1))
    f, st = app.field, app.stretch[1]
    assert st.ready and st.sigma > 0 and st.high >= 30 * st.sigma
    vals, flags, info = compose(f, ViewState(band=1, mode="epoch", visit=10), st)
    fr = f.frames[1][10]
    if fr.available:
        assert vals is fr.image and info["loaded"] and "stacked" not in info

    v = next(i for i, fr in enumerate(f.frames[1]) if fr.available and i > 20)
    diff = ViewState(band=1, mode="diff", visit=v, ref=-1)
    ref = reference(f, diff)
    assert ref >= 0 and ref != v and f.visits[ref].season != f.visits[v].season
    vals, flags, info = compose(f, diff, st)
    assert info["ref"] == ref and info["refLambda"] == f.frames[1][ref].lambda_
    # Background removed: the difference is centered on zero.
    good = ~sky.bad(flags)
    assert abs(float(np.median(vals[good]))) < 3 * st.sigma

    s = ViewState(band=1, mode="sum", visit=v, ref=5)
    vals, flags, info = compose(f, s, st)
    want = sum(1 for i in range(5, v + 1) if f.frames[1][i].available)
    assert info["ref"] == 5 and info["stacked"] == want and info["loaded"]
    # Stacking lowers the noise.
    assert sky.stats(vals, flags)[1] < st.sigma


def test_manual_reference_missing_in_channel_does_not_crash():
    app, rec = sim_app()
    f = app.field
    v = next(i for i, fr in enumerate(f.frames[2]) if fr.available and i > 0)
    f.frames[2][0].available = False
    vals, flags, info = compose(f, ViewState(band=2, mode="diff", visit=v, ref=0), app.stretch[2])
    assert info["ref"] == 0 and vals is None


def test_colorize():
    st = Stretch(ready=True, median=1.0, sigma=0.1, high=3.0)
    vals = np.array([[1.0, 0.0], [1e9, -1e9]], dtype=np.float32)
    g = colorize(vals, ViewState(mode="epoch"), st)
    assert g.shape == (2, 2, 4) and (g[..., 3] == 255).all()
    lo, hi = math.asinh(-0.75), math.asinh(3.0 / 0.1 / 2)
    assert g[0, 0, 0] == int(255 * (0 - lo) / (hi - lo))
    assert g[1, 0, 0] == 255 and g[1, 1, 0] == 0
    d = colorize(np.array([[0.0, 1e9]], dtype=np.float32), ViewState(mode="diff"), st)
    assert d[0, 0, 0] == 127 and d[0, 1, 0] == 255
    t = colorize(np.array([[1e9]], dtype=np.float32), ViewState(mode="epoch", tint=True, band=0), st)
    assert tuple(t[0, 0, :3]) == (255, 255, 255)


def test_events_and_hover():
    app, rec = sim_app(ViewState(band=2, mode="epoch", visit=0, ref=-1, flags=True, catalog=True))
    img = rec.last("image")
    raw = base64.b64decode(img["rgba"])
    assert len(raw) == 59 * 59 * 4 and len(base64.b64decode(img["flags"])) == 59 * 59
    app.set_hover(5, 6)
    h = rec.last("hover")
    assert h["x"] == 5 and h["value"] is not None
    app.set_hover(-1, -1)
    assert rec.last("hover") is None
    ov = rec.last("overlay")
    assert ov["center"] == [29.5, 29.5] and any(c["target"] for c in ov["catalog"])


def test_selection_follows_barnard():
    app, rec = sim_app(ViewState(band=2, mode="epoch", visit=0, ref=-1, catalog=True))
    f = app.field
    v = next(i for i, fr in enumerate(f.frames[2]) if fr.available)
    app.set_view(ViewState(band=2, mode="epoch", visit=v, ref=-1, catalog=True))
    app.update(0.05)
    x, y = f.wcs.to_pixel(*sky.TARGETS[0].source.position(f.visits[v].mjd))
    app.select(x + 0.6, y - 0.4)
    sel = rec.last("select")
    assert sel["moving"] and sel["catalog"]["name"] == "Barnard's Star"
    assert len(sel["track"]) > 10 and sel["measurements"]
    assert rec.last("overlay")["selection"]["points"]
    app.clear_selection()
    assert rec.last("select") is None and rec.last("overlay")["selection"] is None


class FlakyArchive:
    """Lists two images; cutouts fail with a passing error a given number of times."""

    def __init__(self, failures):
        self.failures = failures
        self.cutout = (DATA / "barnard_d6.fits").read_bytes()
        self.calls = 0

    def visits_data(self, ra, dec):
        return json.dumps({"visits": [
            {"path": "ibe/data/spherex/dr1/a/6/level2_A_1_1D6_spx.fits", "mjd": 60902.86, "detector": 6, "exposure": "A_1_1"},
            {"path": "ibe/data/spherex/dr1/a/3/level2_A_1_1D3_spx.fits", "mjd": 60902.86, "detector": 3, "exposure": "A_1_1"},
        ]}).encode(), False

    def catalog_data(self, ra, dec):
        return json.dumps({"sources": [], "missing": ["CatWISE2020"]}).encode(), False

    def cutout_data(self, path, ra, dec, size, cancelled=None):
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise UpstreamError("irsa: cutout: HTTP 503")
        return self.cutout, False


def real_app(failures, both=True):
    rec = Recorder()
    archive = FlakyArchive(failures)
    app = App(rec, archive)
    app.set_view(ViewState(band=5, mode="epoch", visit=0, ref=-1))
    ra, dec = sky.TARGETS[0].source.position(sky.now_mjd())
    app.open(OpenRequest(ra, dec, 6, "", True))
    run_until(app, lambda: rec.last("field") is not None)
    if both:  # switching to channel 3 queues its image too
        app.set_view(ViewState(band=2, mode="epoch", visit=0, ref=-1))
    return app, rec, archive


def test_real_field_loads_only_the_channel_on_screen():
    app, rec, archive = real_app(failures=0, both=False)
    run_until(app, lambda: (rec.last("loaded") or {}).get("done") == 1)
    assert rec.last("loaded")["total"] == 1 and archive.calls == 1
    assert not app.field.frames[2][0].loaded
    # Selecting a source asks for every channel.
    app.select(29.5, 29.5)
    assert rec.last("loaded")["total"] == 2
    run_until(app, lambda: rec.last("loaded")["done"] == 2)
    assert archive.calls == 2 and app.field.frames[2][0].loaded


def test_partial_catalog_is_asked_again(monkeypatch):
    monkeypatch.setattr(app_module, "CATALOG_RETRY", 0.05)
    app, rec, archive = real_app(failures=0, both=False)
    complete = json.dumps({"sources": [{"catalog": "CatWISE2020", "name": "CatWISE x", "ra": 1, "dec": 1,
                                        "pmra": 0, "pmdec": 0, "mjd": 57170, "mag": 9}]}).encode()
    answers = iter([None, complete])
    first = archive.catalog_data

    def catalog_data(ra, dec):
        a = next(answers, complete)
        return (first(ra, dec) if a is None else (a, False))

    archive.catalog_data = catalog_data
    run_until(app, lambda: any(k == "status" and p["stage"] == "catalog" and p["state"] == "done"
                               and "missing" not in p for k, p in rec.events))
    statuses = [p for k, p in rec.events if k == "status" and p["stage"] == "catalog"]
    # One "loading", then partial answers until the complete one.
    assert statuses[0]["state"] == "loading" and all(s["state"] == "done" for s in statuses[1:])
    assert statuses[1]["missing"] == ["CatWISE2020"] and statuses[-1]["count"] == 1
    assert app.field.sources and app.field.sources[0].name == "CatWISE x"


def test_real_field_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(app_module, "CATALOG_ATTEMPTS", 1)
    app, rec, archive = real_app(failures=2)
    assert rec.last("field")["real"]
    run_until(app, lambda: len(app.loader.retry) == 2)
    # Make the retries due now instead of 20 s later.
    app.loader.retry = [(fr, 0.0) for fr, _ in app.loader.retry]
    app.update(0.05)
    run_until(app, lambda: (rec.last("loaded") or {}).get("done") == 2)
    assert archive.calls == 4
    assert all(fr.available for fr in (app.field.frames[5][0], app.field.frames[2][0]))
    run_until(app, lambda: any(k == "status" and p["stage"] == "catalog" and p["state"] == "done"
                               for k, p in rec.events))
    cat = next(p for k, p in reversed(rec.events) if k == "status" and p["stage"] == "catalog")
    assert cat["missing"] == ["CatWISE2020"] and cat["count"] == 0


def test_real_field_gives_up_after_four_retries():
    app, rec, archive = real_app(failures=100)
    for _ in range(app_module.MAX_ATTEMPTS):
        run_until(app, lambda: len(app.loader.retry) == 2)
        app.loader.retry = [(fr, 0.0) for fr, _ in app.loader.retry]
        app.update(0.05)
        assert not app.loader.retry
    run_until(app, lambda: (rec.last("loaded") or {}).get("done") == 2)
    assert archive.calls == 2 * (app_module.MAX_ATTEMPTS + 1)
    assert not app.field.frames[5][0].available and app.field.frames[5][0].loaded


def test_command_validation():
    app = App(Recorder(), None)
    with pytest.raises(ValueError):
        app.command("view", {"band": "2"})
    with pytest.raises(ValueError):
        app.command("open", {"ra": float("nan")})
    with pytest.raises(ValueError):
        app.command("nope", None)
    app.command("view", {"band": 3, "mode": "diff", "visit": 2.0, "ref": -1, "flags": True, "catalog": False, "tint": False})
    app.update(0)
    assert app.view.band == 3 and app.view.visit == 2
