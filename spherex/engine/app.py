"""The engine behind one browser tab.

It owns the field being shown: it plans it (simulated or from the archive),
loads its frames nearest-first around the playhead, composes the image for the
current view, answers hover and selection, and reports everything to the page
as events. The page owns the app state (URL, playback, level) and sends the
view; the engine renders and measures.

All engine state is touched only by the engine thread. UI commands and
download results are posted to it as callables and run in order.
"""

from __future__ import annotations

import collections
import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .. import sky
from ..num import go_round
from ..proxy import BadRequest, Proxy
from .compose import Stretch, ViewState, compose, image_event, overlay

log = logging.getLogger("spherex.engine")

# Downloads in flight per tab, as a browser would allow per host.
MAX_INFLIGHT = 6
# Retries of a cutout the archive keeps failing on: 20, 40, 80, 160 s later.
MAX_ATTEMPTS = 4
# Work done per engine step while simulating frames, so commands stay snappy.
SIM_BUDGET = 0.025
# How often a selection is measured again while frames keep arriving.
SELECTION_INTERVAL = 0.5
# A catalog that came back without CatWISE (IRSA slow or failing) is asked for
# again this often, this many times: CatWISE keeps running in the server and
# lands in its cache, so a later request gets the complete answer.
CATALOG_RETRY = 30.0
CATALOG_ATTEMPTS = 20


def cutout_size(fov: float) -> float:
    """Side of the cutout in degrees. Cutouts come in detector orientation, so
    they must reach the corners of the north-up field at any angle."""
    return fov / 60 * math.sqrt(2) * 1.02


@dataclass
class OpenRequest:
    ra: float = 0.0
    dec: float = 0.0
    fov: float = 0.0
    name: str = ""
    # Real asks for SPHEREx images from the archive instead of the simulation.
    real: bool = False

    @classmethod
    def from_json(cls, d: dict) -> "OpenRequest":
        if not isinstance(d, dict):
            raise ValueError("open request must be an object")

        def num(k):
            v = d.get(k, 0)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{k} must be a number")
            return float(v)

        name, real = d.get("name", ""), d.get("real", False)
        if not isinstance(name, str) or not isinstance(real, bool):
            raise ValueError("bad open request")
        return cls(num("ra"), num("dec"), num("fov"), name, real)


@dataclass
class Selection:
    x: float  # where it was picked, image pixels
    y: float
    visit: int
    band: int
    motion: sky.Motion | None = None
    measurements: list = field(default_factory=list)


class Loader:
    """Brings frames in nearest-first around the playhead in the current
    channel, so playback can start right away.

    Only the channels in `wanted` are queued. Real fields start with the
    channel on screen and add the others when the user switches to them or
    selects a source (whose spectrum needs every channel), so nobody downloads
    six channels to look at one."""

    def __init__(self):
        self.pending: list[sky.Frame] = []
        self.wanted: set[int] = set()
        self.total = 0
        self.done = 0
        self.inflight = 0
        # Frames whose download failed for a passing reason, back in the queue
        # after a delay; attempts counts the tries per frame.
        self.retry: list[tuple[sky.Frame, float]] = []
        self.attempts: dict[int, int] = {}

    def reset(self, f: sky.Field, channels=None) -> None:
        """Start over for a field, queueing `channels` (default: all)."""
        self.pending, self.retry, self.attempts = [], [], {}
        self.wanted = set()
        self.done = self.inflight = self.total = 0
        if f.real:
            # Gaps in coverage count as loaded: there is nothing to fetch.
            for c in range(sky.NUM_CHANNELS):
                for fr in f.frames[c]:
                    if not fr.available:
                        fr.loaded = True
        self.want(f, range(sky.NUM_CHANNELS) if channels is None else channels)

    def want(self, f: sky.Field, channels) -> bool:
        """Queue the frames of channels not wanted yet; True if any were added."""
        added = False
        for c in channels:
            if c in self.wanted:
                continue
            self.wanted.add(c)
            added = True
            for fr in f.frames[c]:
                if not fr.loaded:
                    self.pending.append(fr)
                    self.total += 1
        return added

    def next(self, v: ViewState) -> sky.Frame | None:
        best, score = -1, math.inf
        for i, fr in enumerate(self.pending):
            s = abs(fr.visit - v.visit) + (10000 if fr.channel != v.band else 0)
            if s < score:
                best, score = i, s
        if best < 0:
            return None
        fr = self.pending[best]
        self.pending[best] = self.pending[-1]
        self.pending.pop()
        return fr


def targets_info(now_mjd: float) -> list[dict]:
    out = []
    for t in sky.TARGETS:
        ra, dec = t.source.position(now_mjd)
        out.append({"id": t.id, "name": t.name, "aliases": t.aliases, "ra": ra, "dec": dec,
                    "pmra": t.source.pmra, "pmdec": t.source.pmdec, "band": t.band, "mode": t.mode})
    return out


class App:
    def __init__(self, emit: Callable[[str, object], None], archive: Proxy | None):
        self.emit = emit
        # Where real data comes from; None means simulated data only.
        self.archive = archive
        # Changes with every open, so answers for an older field are dropped.
        self.gen = 0
        self.field: sky.Field | None = None
        self.view = ViewState()
        self.stretch = [Stretch() for _ in range(sky.NUM_CHANNELS)]
        self.loader = Loader()
        self.sel: Selection | None = None
        self.hover_xy = (-1, -1)
        # Result of the last composition, for the hover readout.
        self.shown = None
        self.shown_flags = None
        self.dirty = False
        self.sel_dirty = False
        self.sel_timer = 0.0

        self._queue: collections.deque[Callable[[], None]] = collections.deque()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=MAX_INFLIGHT + 2, thread_name_prefix="engine-io")
        self._thread: threading.Thread | None = None

    # ---------- lifecycle ----------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="engine")
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        self._wake.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def post(self, fn: Callable[[], None]) -> None:
        """Queue work to run on the engine thread."""
        self._queue.append(fn)
        self._wake.set()

    def _run(self) -> None:
        last = time.monotonic()
        while not self._closed.is_set():
            busy = self.field is not None and not self.field.real and bool(self.loader.pending)
            self._wake.wait(0.002 if busy else 0.05)
            self._wake.clear()
            now = time.monotonic()
            dt, last = now - last, now
            try:
                self.update(dt)
            except Exception:
                log.exception("engine step failed")

    def _drain(self) -> None:
        while self._queue:
            fn = self._queue.popleft()
            try:
                fn()
            except Exception:
                log.exception("engine command failed")

    # ---------- commands from the page ----------

    def command(self, name: str, args) -> None:
        """Validate a command from the page and queue it."""
        if name == "open":
            req = OpenRequest.from_json(args)
            self.post(lambda: self.open(req))
        elif name == "view":
            v = ViewState.from_json(args)
            self.post(lambda: self.set_view(v))
        elif name == "select":
            x, y = float(args["x"]), float(args["y"])
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("x and y must be finite")
            self.post(lambda: self.select(x, y))
        elif name == "hover":
            if args is None:
                xy = (-1, -1)
            else:
                xy = (int(args["x"]), int(args["y"]))
            self.post(lambda: self.set_hover(*xy))
        elif name == "clearSelection":
            self.post(self.clear_selection)
        else:
            raise ValueError(f"unknown command {name!r}")

    def ready(self) -> None:
        self.emit("ready", {"targets": targets_info(sky.now_mjd())})

    def open(self, req: OpenRequest) -> None:
        self.gen += 1
        # A fast mover's current position changes the 6-decimal center every
        # few hours; rounding to 1.8" keeps the archive requests, and so the
        # cache and its warm-up entries, the same for weeks.
        req.ra = go_round(req.ra * 2000) / 2000
        req.dec = go_round(req.dec * 2000) / 2000
        fov = max(4.0, min(12.0, req.fov))
        if req.real and self.archive is not None:
            self._open_real(req, fov)
            return
        f = sky.new_field(req.ra, req.dec, fov, sky.now_mjd())
        if not f.name:
            f.name = req.name
        self._start_field(f, req, fov)

    def set_view(self, v: ViewState) -> None:
        if v.band < 0 or v.band >= sky.NUM_CHANNELS:
            v.band = self.view.band
        if self.field is not None:
            v.visit = max(0, min(v.visit, len(self.field.visits) - 1))
            self._want([v.band])
        self.view = v
        self.dirty = True

    def _want(self, channels) -> None:
        """Make sure the frames of these channels get loaded, and tell the page
        the new total."""
        if self.field is not None and self.loader.want(self.field, channels):
            self.emit("loaded", {"items": [], "done": self.loader.done, "total": self.loader.total})

    def set_hover(self, x: int, y: int) -> None:
        self.hover_xy = (x, y)
        self.hover(x, y)

    def select(self, x: float, y: float) -> None:
        f, v = self.field, self.view
        if f is None:
            return
        fr = f.frames[v.band][v.visit]
        if fr.loaded and fr.available:
            cx, cy, snr = sky.centroid(fr, f.n, x, y, 2)
            if snr >= 5:
                x, y = cx, cy
        self.sel = Selection(x=x, y=y, visit=v.visit, band=v.band)
        # The spectrum needs every channel.
        self._want(range(sky.NUM_CHANNELS))
        self._measure_selection()

    def clear_selection(self) -> None:
        self.sel = None
        self.emit("select", None)
        self._emit_overlay()

    # ---------- fields ----------

    def _start_field(self, f: sky.Field, req: OpenRequest, fov: float) -> None:
        self.field = f
        self.stretch = [Stretch() for _ in range(sky.NUM_CHANNELS)]
        self.sel = None
        self.shown = self.shown_flags = None
        # Simulated frames cost no download, so they all load at once.
        self.loader.reset(f, [self.view.band] if f.real else None)
        self.dirty = True
        self.view.visit = min(self.view.visit, max(0, len(f.visits) - 1))
        self.emit("field", {
            "target": f.target_id, "name": f.name, "ra": req.ra, "dec": req.dec, "fov": fov,
            "npix": f.n, "pixscale": sky.PIX_SCALE, "real": f.real, "fluxUnit": f.flux_unit,
            "visits": [{"mjd": v.mjd, "date": sky.mjd_to_iso_date(v.mjd), "season": v.season,
                        "sub": int(go_round(v.sub_band))} for v in f.visits],
            "channels": [{"lo": ch.lo, "hi": ch.hi, "available": [fr.available for fr in f.frames[c]]}
                         for c, ch in enumerate(sky.CHANNELS)],
            # Cutout side in pixels, for the download estimate.
            "frameSize": int(math.ceil(cutout_size(fov) * 3600 / sky.PIX_SCALE)),
        })
        self.emit("loaded", {"items": [], "done": 0, "total": self.loader.total})
        self.emit("select", None)

    def _open_real(self, req: OpenRequest, fov: float) -> None:
        gen = self.gen
        self.field = None
        self.sel = None
        self.emit("status", {"stage": "visits", "state": "loading"})

        def work():
            err, images = None, []
            try:
                body, _ = self.archive.visits_data(req.ra, req.dec)
                images = [sky.ArchiveImage.from_json(d) for d in json.loads(body)["visits"]]
            except Exception as e:
                err = e

            def done():
                if gen != self.gen:
                    return
                if err is not None:
                    self.emit("status", {"stage": "visits", "state": "error", "error": str(err)})
                    return
                if not images:
                    self.emit("status", {"stage": "visits", "state": "empty"})
                    return
                f = sky.new_real_field(req.ra, req.dec, fov, images, sky.now_mjd())
                if not f.name:
                    f.name = req.name
                self.emit("status", {"stage": "visits", "state": "done", "count": len(images)})
                self._start_field(f, req, fov)
                self._fetch_catalog(f)

            self.post(done)

        self._pool.submit(work)

    def _fetch_catalog(self, f: sky.Field, attempt: int = 0) -> None:
        gen = self.gen
        if attempt == 0:
            self.emit("status", {"stage": "catalog", "state": "loading"})

        def work():
            err, sources, missing = None, [], []
            try:
                body, _ = self.archive.catalog_data(f.wcs.ra, f.wcs.dec)
                res = json.loads(body)
                sources = [sky.CatalogEntry.from_json(d) for d in res.get("sources") or []]
                missing = res.get("missing") or []
            except Exception as e:
                err = e

            def done():
                if gen != self.gen:
                    return
                if err is not None:
                    if attempt == 0:
                        self.emit("status", {"stage": "catalog", "state": "error", "error": str(err)})
                    return
                sky.set_catalog(f, sources)
                self.sel_dirty = True
                ev = {"stage": "catalog", "state": "done", "count": len(sources)}
                if missing:
                    ev["missing"] = missing
                    if attempt + 1 < CATALOG_ATTEMPTS:
                        self._later(CATALOG_RETRY, gen, lambda: self._fetch_catalog(f, attempt + 1))
                self.emit("status", ev)
                self._emit_overlay()

            self.post(done)

        threading.Thread(target=work, daemon=True, name="catalog").start()

    def _later(self, delay: float, gen: int, fn: Callable[[], None]) -> None:
        """Run fn on the engine thread after delay seconds, unless another
        field has been opened by then."""
        def fire():
            if gen == self.gen and not self.closed:
                fn()

        t = threading.Timer(delay, lambda: self.post(fire))
        t.daemon = True
        t.start()

    def _fetch_cutout(self, fr: sky.Frame) -> None:
        gen, f = self.gen, self.field
        ra, dec, size = f.wcs.ra, f.wcs.dec, cutout_size(f.fov)

        def work():
            body, err, transient = None, None, False
            try:
                body, _ = self.archive.cutout_data(fr.file, ra, dec, size,
                                                   cancelled=lambda: gen != self.gen or self.closed)
            except BadRequest as e:
                err = e
            except Exception as e:  # the archive failed or the field changed
                err, transient = e, True

            def done():
                if gen != self.gen:
                    return
                l = self.loader
                l.inflight -= 1
                nonlocal err
                key = id(fr)
                if transient and l.attempts.get(key, 0) < MAX_ATTEMPTS:
                    l.attempts[key] = l.attempts.get(key, 0) + 1
                    l.retry.append((fr, time.monotonic() + (10 << l.attempts[key])))
                    return
                if err is None:
                    try:
                        sky.load_cutout(f, fr, body)
                    except Exception as e:
                        err = e
                if err is not None:
                    # A frame that cannot be read is shown as missing, like a gap in coverage.
                    log.info("cutout %s: %s", fr.file, err)
                    fr.loaded, fr.available = True, False
                ev = {"items": [], "done": 0, "total": 0}
                self._frame_loaded(fr, ev)
                self.emit("loaded", ev)

            self.post(done)

        try:
            self._pool.submit(work)
        except RuntimeError:  # closed
            pass

    def _frame_loaded(self, fr: sky.Frame, ev: dict) -> None:
        self.loader.done += 1
        ev["items"].append({"c": fr.channel, "v": fr.visit, "l": fr.lambda_, "a": fr.available})
        ev["done"], ev["total"] = self.loader.done, self.loader.total
        self._init_stretch(fr)
        if fr.channel == self.view.band or self.view.mode == "diff":
            self.dirty = True
        self.sel_dirty = True

    def _init_stretch(self, fr: sky.Frame) -> None:
        st = self.stretch[fr.channel]
        if st.ready or not fr.available:
            return
        st.median, st.sigma = fr.background, fr.sigma
        st.high = max(sky.percentile(fr.image, fr.flags, 0.998) - st.median, 30 * st.sigma)
        st.ready = True

    # ---------- the engine step ----------

    def update(self, dt: float) -> None:
        self._drain()
        f = self.field
        if f is None:
            return
        l = self.loader
        ev = {"items": [], "done": 0, "total": 0}
        if f.real:
            now = time.monotonic()
            due = [r for r in l.retry if now >= r[1]]
            if due:
                l.retry = [r for r in l.retry if now < r[1]]
                l.pending.extend(fr for fr, _ in due)
            while l.inflight < MAX_INFLIGHT and l.pending:
                l.inflight += 1
                self._fetch_cutout(l.next(self.view))
        else:
            start = time.monotonic()
            while l.pending and time.monotonic() - start < SIM_BUDGET:
                fr = l.next(self.view)
                f.load(fr)
                self._frame_loaded(fr, ev)
        if ev["items"]:
            self.emit("loaded", ev)

        if self.dirty:
            self._compose()
            self.dirty = False
            if self.hover_xy[0] >= 0:
                self.hover(*self.hover_xy)

        self.sel_timer -= dt
        if self.sel is not None and self.sel_dirty and self.sel_timer <= 0:
            self._measure_selection()

    def _compose(self) -> None:
        f, v = self.field, self.view
        st = self.stretch[v.band]
        fr = f.frames[v.band][v.visit]
        vals, flags, info = compose(f, v, st)
        if vals is not None and st.ready:
            self.shown, self.shown_flags = vals, flags
            self.emit("image", image_event(f, vals, flags, v, st))
        elif fr.loaded and not fr.available:
            self.shown = self.shown_flags = None
            self.emit("image", image_event(f, None, None, v, st))
        self.emit("frame", info)
        self._emit_overlay()

    def _emit_overlay(self) -> None:
        if self.field is not None:
            self.emit("overlay", overlay(self.field, self.view, self.sel))

    def hover(self, px: int, py: int) -> None:
        f = self.field
        if f is None or px < 0 or py < 0 or px >= f.n or py >= f.n:
            self.emit("hover", None)
            return
        ra, dec = f.wcs.to_sky(px + 0.5, py + 0.5)
        ev = {"x": px, "y": py, "ra": ra, "dec": dec, "value": None, "flags": None}
        if self.shown is not None:
            ev["value"] = float(self.shown[py, px])
            names = sky.flag_names(int(self.shown_flags[py, px])) if self.shown_flags is not None else []
            ev["flags"] = names or None
        self.emit("hover", ev)

    def _measure_selection(self) -> None:
        f, s = self.field, self.sel
        if f is None or s is None:
            return
        s.motion = sky.track(f, s.band, s.visit, s.x, s.y)
        s.measurements = sky.measure(f, s.motion)
        self.sel_dirty = False
        self.sel_timer = SELECTION_INTERVAL

        mjd = f.visits[s.visit].mjd
        x, y = s.motion.at(mjd)
        ra, dec = f.wcs.to_sky(x, y)
        pmra, pmdec = s.motion.proper_motion()
        era, edec = s.motion.proper_motion_err()
        ev = {
            "ra": ra, "dec": dec, "band": s.band, "moving": s.motion.moving,
            "pmra": pmra, "pmdec": pmdec, "pmraErr": era, "pmdecErr": edec,
            "track": [p.to_json() for p in s.motion.points],
            "measurements": [m.to_json() for m in s.measurements],
            "catalog": None,
        }
        best = 1.5
        for src in f.sources:
            if not src.catalog:
                continue
            sx, sy = f.wcs.to_pixel(*src.position(mjd))
            d = math.hypot(sx - x, sy - y)
            if d < best:
                best = d
                ev["catalog"] = {"name": src.name or "Gaia DR3", "pmra": src.pmra / 1000, "pmdec": src.pmdec / 1000}
        self.emit("select", ev)
        self._emit_overlay()

