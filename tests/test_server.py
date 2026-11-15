"""The server and the engine end to end over HTTP: simulation, and the
real-data path against local stand-ins for IRSA and the Gaia CDN."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from spherex import fits, gaia, irsa
from spherex.proxy import Proxy
from spherex.server import UI_DIR, make_server

from .fake_archive import FakeArchive, barnard_position


class Client:
    """Talks to the server like the page does: an event stream and commands."""

    def __init__(self, base: str, session: str = "testsession01"):
        self.base, self.session = base, session
        self.events: list[tuple[str, dict]] = []
        self._cond = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        r = urllib.request.urlopen(f"{self.base}/api/engine/events?session={self.session}", timeout=120)
        kind = None
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                with self._cond:
                    self.events.append((kind, json.loads(line[6:])))
                    self._cond.notify_all()

    def wait(self, pred, timeout=30.0):
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for k, d in reversed(self.events):
                    if pred(k, d):
                        return d
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"timed out; events: {[k for k, _ in self.events][-30:]}")
                self._cond.wait(left)

    def last(self, kind):
        with self._cond:
            return next((d for k, d in reversed(self.events) if k == kind), None)

    def cmd(self, cmd, args=None):
        body = json.dumps({"session": self.session, "cmd": cmd, "args": args}).encode()
        req = urllib.request.Request(f"{self.base}/api/engine/command", data=body,
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10).status


def serve(proxy):
    httpd = make_server(("127.0.0.1", 0), UI_DIR, proxy)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


VIEW = {"band": 1, "mode": "epoch", "visit": 0, "ref": -1, "flags": True, "catalog": True, "tint": False}


def test_simulation_session():
    httpd, base = serve(None)
    try:
        status, _, body = get(base + "/api/health")
        assert status == 200 and json.loads(body)["ok"] is False
        assert get(base + "/")[0] == 200 and get(base + "/engine.js")[0] == 200
        assert get(base + "/api/visits?ra=1&dec=1")[0] == 502
        c = Client(base)
        ready = c.wait(lambda k, d: k == "ready")
        barnard = next(t for t in ready["targets"] if t["id"] == "barnard")
        assert c.cmd("view", VIEW) == 200
        c.cmd("open", {"ra": barnard["ra"], "dec": barnard["dec"], "fov": 6, "name": "x", "real": True})
        field = c.wait(lambda k, d: k == "field")
        assert field["name"] == "Barnard's Star" and not field["real"] and field["npix"] == 59
        c.wait(lambda k, d: k == "loaded" and d["done"] == d["total"])
        img = c.wait(lambda k, d: k == "image" and d["rgba"])
        assert img["n"] == 59 and img["flags"] is not None
        ov = c.wait(lambda k, d: k == "overlay" and d["catalog"])
        target = next(e for e in ov["catalog"] if e["target"])
        c.cmd("view", {**VIEW, "mode": "diff"})
        c.cmd("select", {"x": target["x1"], "y": target["y1"]})
        sel = c.wait(lambda k, d: k == "select" and d)
        assert sel["moving"] and sel["catalog"]["name"] == "Barnard's Star"
        assert abs(sel["pmdec"] - 10.36) < 0.8 and abs(sel["pmra"] + 0.8) < 0.8
        c.cmd("clearSelection")
        c.wait(lambda k, d: k == "select" and d is None)
        # Bad commands are refused without hurting the session.
        req = urllib.request.Request(base + "/api/engine/command", data=b'{"session":"testsession01","cmd":"view","args":{"band":"x"}}')
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 400
        assert c.cmd("hover", {"x": 3, "y": 4}) == 200
        assert c.wait(lambda k, d: k == "hover" and d and d["x"] == 3)["value"] is not None
    finally:
        httpd.shutdown()


@pytest.fixture
def real(tmp_path):
    fake = FakeArchive(cutout_failures=1)
    proxy = Proxy(irsa.Client(fake.url, 4), irsa.Cache(tmp_path),
                  gaia.Store(tmp_path / "gaia", base=fake.url + "/gaia/files/", list_url=fake.url + "/gaia/list?x=1",
                             chunk=1024))
    httpd, base = serve(proxy)
    yield fake, proxy, base
    httpd.shutdown()
    fake.close()


def test_proxy_endpoints(real):
    fake, proxy, base = real
    ra, dec = barnard_position()
    status, headers, body = get(f"{base}/api/visits?ra={ra}&dec={dec}")
    assert status == 200 and headers["X-Cache"] == "MISS" and headers["Access-Control-Allow-Origin"] == "*"
    v = json.loads(body)
    assert v["source"] == "SIA" and len(v["visits"]) == 36
    assert get(f"{base}/api/visits?ra={ra}&dec={dec}")[1]["X-Cache"] == "HIT"
    path = v["visits"][0]["path"]
    status, headers, body = get(f"{base}/api/cutout?path={path}&ra={ra:.6f}&dec={dec:.6f}&size=0.1")
    assert status == 200 and headers["Content-Type"] == "application/fits"
    assert "EPSF" not in [h.name() for h in fits.parse(body)]
    for bad in ("path=ibe/data/wise/x.fits&ra=1&dec=1&size=0.1", f"path={path}&ra=1&dec=1&size=0.5",
                f"path={path}&ra=400&dec=1&size=0.1", "ra=nan&dec=1"):
        assert get(f"{base}/api/cutout?{bad}")[0] == 400, bad
    status, _, body = get(f"{base}/api/catalog?ra={ra}&dec={dec}")
    cat = json.loads(body)
    assert status == 200 and "missing" not in cat
    names = [s["name"] for s in cat["sources"]]
    assert any(n.startswith("Gaia DR3") for n in names)
    # CatWISE's Barnard entry is a duplicate of Gaia's and is dropped.
    assert not any(n.startswith("CatWISE") for n in names)
    assert get(f"{base}/api/catalog?ra={ra}&dec={dec}")[1]["X-Cache"] == "HIT"
    assert json.loads(get(f"{base}/api/gaia/progress?ra={ra}&dec={dec}")[2]) == []


def test_real_session(real):
    fake, proxy, base = real
    ra, dec = barnard_position()
    c = Client(base, "realsession1")
    c.wait(lambda k, d: k == "ready")
    # Exposure 3 of each season covers detectors 3 and 6.
    c.cmd("view", {**VIEW, "band": 5, "visit": 2})
    c.cmd("open", {"ra": ra, "dec": dec, "fov": 6, "name": "", "real": True})
    c.wait(lambda k, d: k == "status" and d["stage"] == "visits" and d["state"] == "done")
    field = c.wait(lambda k, d: k == "field")
    assert field["real"] and field["fluxUnit"] == "mJy" and len(field["visits"]) == 18
    assert sum(field["channels"][5]["available"]) == 6
    c.wait(lambda k, d: k == "status" and d["stage"] == "catalog" and d["state"] == "done", timeout=60)
    # Only the channel on screen is downloaded at first: 6 images of detector 6.
    loaded = c.wait(lambda k, d: k == "loaded" and d["total"] and d["done"] == d["total"], timeout=60)
    assert loaded["total"] == 6
    assert len({c[0] for c in fake.server.calls_to("/ibe/")}) == 6  # one of them was retried after a 503
    frame = c.wait(lambda k, d: k == "frame" and d["loaded"] and d["available"])
    assert abs(frame["lambda"] - 4.93) < 0.05
    ov = c.wait(lambda k, d: k == "overlay" and any(e["target"] for e in d["catalog"]))
    target = next(e for e in ov["catalog"] if e["target"])
    c.cmd("select", {"x": target["x1"], "y": target["y1"]})
    sel = c.wait(lambda k, d: k == "select" and d)
    assert sel["catalog"]["name"] == "Barnard's Star"
    # Selecting a source brings in the other channels for its spectrum.
    c.wait(lambda k, d: k == "loaded" and d["total"] == 36 and d["done"] == 36, timeout=60)
    sel = c.wait(lambda k, d: k == "select" and d and len({m["c"] for m in d["measurements"]}) == 6)
    # The stand-in serves the same cutout for every detector, so all six channels are measured.
    assert {m["c"] for m in sel["measurements"]} == set(range(6))
    # Opening another field drops the answers for this one.
    c.cmd("open", {"ra": 10.0, "dec": 10.0, "fov": 6, "name": "", "real": False})
    f2 = c.wait(lambda k, d: k == "field" and not d["real"])
    assert f2["ra"] == 10.0


def test_catalog_does_not_wait_twice_for_catwise(tmp_path, monkeypatch):
    """A second request while CatWISE is still running answers right away."""
    from spherex import proxy as proxy_module

    monkeypatch.setattr(proxy_module, "CATWISE_GRACE", 1.5)
    release = threading.Event()

    class SlowClient:
        def catwise(self, ra, dec, radius):
            release.wait(30)
            return []

    class NoGaia:
        def cone(self, ra, dec, radius, timeout):
            return []

    p = Proxy(SlowClient(), irsa.Cache(tmp_path), NoGaia())
    t0 = time.monotonic()
    data, _ = p.catalog_data(10, 10)
    first = time.monotonic() - t0
    assert json.loads(data)["missing"] == ["CatWISE2020"] and first >= 1.5
    t0 = time.monotonic()
    data, _ = p.catalog_data(10, 10)
    assert json.loads(data)["missing"] == ["CatWISE2020"] and time.monotonic() - t0 < 1.4
    release.set()
    deadline = time.monotonic() + 10
    while True:
        data, _ = p.catalog_data(10, 10)
        if "missing" not in json.loads(data):
            break
        assert time.monotonic() < deadline
        time.sleep(0.05)
