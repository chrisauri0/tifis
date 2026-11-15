"""HTTP server: the web app, the /api/* proxy and the engine API.

    GET  /api/health                       {"ok": true}, or {"ok": false} with --sim
    GET  /api/visits?ra=&dec=              spectral images covering a position (JSON)
    GET  /api/cutout?path=&ra=&dec=&size=  cutout without the PSF cube (FITS)
    GET  /api/catalog?ra=&dec=             Gaia DR3 and CatWISE2020 sources nearby (JSON)
    GET  /api/gaia/progress?ra=&dec=       Gaia bulk files being streamed for a field (JSON)
    GET  /api/features                     spectral features and classification rules (JSON)
    GET  /api/engine/events?session=       engine events for one tab (Server-Sent Events)
    POST /api/engine/command               {"session", "cmd", "args"} from the page
    GET  /...                              files of the web app (ui/)

IRSA sends no CORS headers, so browsers cannot query it directly; the server
relays it and serves the app from the same origin.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import math
import os
import re
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import features, gaia, irsa
from .engine import App
from .num import parse_float
from .proxy import BadRequest, Proxy, UpstreamError

log = logging.getLogger("spherex")

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
# Polled by the page every few seconds; logged only when they fail.
QUIET = frozenset({"/api/health", "/api/gaia/progress", "/api/features"})
# Coalesced when several are waiting: only the newest of each matters.
COALESCE = frozenset({"image", "overlay", "frame", "hover", "analysis"})
SESSION_IDLE = 60.0  # seconds without an event stream before a tab's engine stops
KEEPALIVE = 15.0
MAX_COMMAND = 64 * 1024
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def user_cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


class Session:
    """One browser tab: its engine and the events waiting for its stream."""

    def __init__(self, sid: str, archive: Proxy | None):
        self.sid = sid
        self._events: collections.deque[tuple[str, str]] = collections.deque()
        self._cond = threading.Condition()
        self._conn = 0  # id of the current event stream
        self.streams = 0
        self.last_seen = time.monotonic()
        self.ready_sent = False
        self.app = App(self._emit, archive)
        self.app.start()

    def _emit(self, kind: str, payload) -> None:
        try:
            data = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError) as e:
            log.warning("engine event %s dropped: %s", kind, e)
            return
        with self._cond:
            self._events.append((kind, data))
            self._cond.notify_all()

    def attach(self) -> int:
        with self._cond:
            self._conn += 1
            self.streams += 1
            self.last_seen = time.monotonic()
            self._cond.notify_all()
            conn = self._conn
            first = not self.ready_sent
            self.ready_sent = True
        if first:
            self.app.ready()
        return conn

    def detach(self) -> None:
        with self._cond:
            self.streams -= 1
            self.last_seen = time.monotonic()

    def next_batch(self, conn: int, timeout: float) -> list[tuple[str, str]] | None:
        """Waiting events, newest image/overlay/frame/hover only; [] on timeout,
        None once a newer stream has taken over."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._events and conn == self._conn:
                left = deadline - time.monotonic()
                if left <= 0:
                    return []
                self._cond.wait(left)
            if conn != self._conn:
                return None
            batch = list(self._events)
            self._events.clear()
            self.last_seen = time.monotonic()
        last = {kind: i for i, (kind, _) in enumerate(batch) if kind in COALESCE}
        return [e for i, e in enumerate(batch) if e[0] not in COALESCE or last[e[0]] == i]

    def idle(self) -> float:
        with self._cond:
            return 0.0 if self.streams > 0 else time.monotonic() - self.last_seen

    def close(self) -> None:
        self.app.close()
        with self._cond:
            self._conn += 1
            self._cond.notify_all()


class Sessions:
    def __init__(self, archive: Proxy | None):
        self.archive = archive
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        threading.Thread(target=self._reap, daemon=True, name="sessions").start()

    def get(self, sid: str, create: bool = False) -> Session | None:
        with self._lock:
            s = self._sessions.get(sid)
            if s is None and create:
                s = self._sessions[sid] = Session(sid, self.archive)
            return s

    def _reap(self) -> None:
        while True:
            time.sleep(5)
            with self._lock:
                old = [sid for sid, s in self._sessions.items() if s.idle() > SESSION_IDLE]
                closing = [self._sessions.pop(sid) for sid in old]
            for s in closing:
                s.close()


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "spherex-sky-timeline"
    # Set by make_server.
    proxy: Proxy | None = None
    sessions: Sessions | None = None
    sim_only = False

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    # ---------- plumbing ----------

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            # Make the browser revalidate the app files, so an edit shows up on reload.
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        # Always send the current file. Files unpacked from a zip keep old
        # timestamps, so answering If-Modified-Since with 304 would let the
        # browser keep a newer-dated copy of a previous version of the app.
        del self.headers["If-Modified-Since"]
        del self.headers["If-None-Match"]
        return super().send_head()

    def log_request(self, code="-", size="-"):
        code = int(code) if str(code).isdigit() else 0
        path = urlsplit(self.path).path
        api = path.startswith("/api/") and not path.startswith("/api/engine/") and path not in QUIET
        if api or code >= 400:
            log.info("%s %s %s %dms", self.command, self.path, code,
                     round((time.monotonic() - getattr(self, "_start", time.monotonic())) * 1000))

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def send_bytes(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, code: int, value, headers: dict | None = None):
        self.send_bytes(code, json.dumps(value, separators=(",", ":")).encode() + b"\n", "application/json", headers)

    def send_error_json(self, code: int, msg: str):
        self.send_json(code, {"error": msg})

    def query(self) -> dict[str, str]:
        q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        return {k: v[0] for k, v in q.items()}

    def position(self, q) -> tuple[float, float]:
        try:
            ra, dec = parse_float(q.get("ra", "")), parse_float(q.get("dec", ""))
        except ValueError:
            raise BadRequest("ra must be in [0, 360) and dec in [-90, 90] degrees") from None
        if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
            raise BadRequest("ra must be in [0, 360) and dec in [-90, 90] degrees")
        return ra, dec

    # ---------- routes ----------

    def do_GET(self):
        self._start = time.monotonic()
        path = urlsplit(self.path).path
        routes = {
            "/api/health": self.api_health,
            "/api/visits": self.api_visits,
            "/api/cutout": self.api_cutout,
            "/api/catalog": self.api_catalog,
            "/api/gaia/progress": self.api_gaia_progress,
            "/api/features": self.api_features,
            "/api/engine/events": self.api_events,
        }
        if path in routes:
            try:
                routes[path]()
            except BadRequest as e:
                self.send_error_json(400, str(e))
            except UpstreamError as e:
                self.send_error_json(502, str(e))
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            return
        if path.startswith("/api/"):
            self.send_error_json(404, "not found")
            return
        super().do_GET()

    def do_HEAD(self):
        self._start = time.monotonic()
        if urlsplit(self.path).path.startswith("/api/"):
            self.send_error_json(405, "method not allowed")
            return
        super().do_HEAD()

    def do_POST(self):
        self._start = time.monotonic()
        if urlsplit(self.path).path != "/api/engine/command":
            self.send_error_json(404, "not found")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > MAX_COMMAND:
            self.close_connection = True
            self.send_error_json(413 if n > 0 else 400, "bad body")
            return
        try:
            msg = json.loads(self.rfile.read(n) or b"null")
            sid, cmd = msg["session"], msg["cmd"]
            if not isinstance(sid, str) or not isinstance(cmd, str):
                raise ValueError("session and cmd must be strings")
        except (ValueError, KeyError, TypeError) as e:
            self.send_error_json(400, f"bad command: {e}")
            return
        s = self.sessions.get(sid)
        if s is None:
            self.send_error_json(404, "unknown session")
            return
        try:
            s.app.command(cmd, msg.get("args"))
        except (ValueError, KeyError, TypeError) as e:
            self.send_error_json(400, f"bad command: {e}")
            return
        self.send_bytes(200, b"{}\n", "application/json")

    def api_health(self):
        if self.sim_only:
            # The page reads ok:false as "use the simulation".
            self.send_json(200, {"ok": False, "sim": True})
        else:
            self.send_json(200, {"ok": True})

    def api_features(self):
        # The same table the analysis uses, so the page never keeps its own copy.
        self.send_json(200, features.as_json(), {"Cache-Control": "no-cache"})

    def _need_proxy(self) -> Proxy:
        if self.proxy is None:
            raise UpstreamError("simulation only (--sim)")
        return self.proxy

    def api_visits(self):
        q = self.query()
        data, hit = self._need_proxy().visits_data(*self.position(q))
        self.send_bytes(200, data, "application/json", {"X-Cache": "HIT" if hit else "MISS"})

    def api_catalog(self):
        q = self.query()
        data, hit = self._need_proxy().catalog_data(*self.position(q))
        self.send_bytes(200, data, "application/json", {"X-Cache": "HIT" if hit else "MISS"})

    def api_gaia_progress(self):
        q = self.query()
        ra, dec = self.position(q)
        self.send_json(200, self._need_proxy().gaia_progress(ra, dec))

    def api_cutout(self):
        q = self.query()
        ra, dec = self.position(q)
        proxy = self._need_proxy()
        path = q.get("path", "")
        if not irsa.valid_path(path):
            raise BadRequest("path must be a SPHEREx archive file")
        try:
            size = parse_float(q.get("size", ""))
        except ValueError:
            size = math.nan
        if not (0 < size <= 0.3):
            raise BadRequest("size must be in (0, 0.3] degrees")
        data, hit = proxy.cutout_data(path, ra, dec, size)
        # Archive paths carry their processing version, so a cutout never changes.
        self.send_bytes(200, data, "application/fits", {
            "Cache-Control": "public, max-age=31536000, immutable", "X-Cache": "HIT" if hit else "MISS"})

    def api_events(self):
        sid = self.query().get("session", "")
        if not _SESSION_RE.fullmatch(sid):
            raise BadRequest("session must be 8-64 letters, digits, - or _")
        s = self.sessions.get(sid, create=True)
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        conn = s.attach()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                batch = s.next_batch(conn, KEEPALIVE)
                if batch is None:
                    return
                if not batch:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    self.wfile.write("".join(f"event: {k}\ndata: {d}\n\n" for k, d in batch).encode())
                self.wfile.flush()
        except OSError:
            pass
        finally:
            s.detach()


def make_server(addr: tuple[str, int], web: Path, proxy: Proxy | None) -> ThreadingHTTPServer:
    sessions = Sessions(proxy)

    class H(Handler):
        pass

    H.proxy, H.sessions, H.sim_only = proxy, sessions, proxy is None

    def factory(*args, **kwargs):
        return H(*args, directory=str(web), **kwargs)

    httpd = ThreadingHTTPServer(addr, factory)
    httpd.daemon_threads = True
    return httpd


def parse_addr(addr: str) -> tuple[str, int]:
    host, sep, port = addr.rpartition(":")
    if not sep:
        host, port = "", addr
    return host.strip("[]"), int(port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m spherex",
                                description="Tifis: web app, IRSA/Gaia proxy and engine.")
    p.add_argument("--addr", default=":" + os.environ.get("PORT", "8080"),
                   help="listen address, e.g. :8080 or 127.0.0.1:8080 (default :$PORT or :8080)")
    p.add_argument("--web", type=Path, default=UI_DIR, help="directory with the web app (default: ui/)")
    p.add_argument("--cache", type=Path, default=user_cache_dir() / "spherex-proxy", help="cache directory")
    p.add_argument("--irsa", default=irsa.DEFAULT_BASE, help="IRSA base URL")
    p.add_argument("--gaia-base", default=gaia.DEFAULT_BASE, help="Gaia DR3 bulk files URL")
    p.add_argument("--gaia-list", default=gaia.DEFAULT_LIST, help="Gaia DR3 bucket listing URL")
    p.add_argument("--parallel", type=int, default=8, help="concurrent requests to IRSA")
    p.add_argument("--sim", action="store_true", help="simulated data only: no IRSA, no Gaia, no network")
    p.add_argument("--no-warm", action="store_true", help="skip fetching the test objects at startup")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
    if not (a.web / "index.html").is_file():
        p.error(f"{a.web} has no index.html")
    proxy = None
    if not a.sim:
        cache = irsa.Cache(a.cache)
        store = gaia.Store(a.cache / "gaia", base=a.gaia_base, list_url=a.gaia_list)
        proxy = Proxy(irsa.Client(a.irsa, a.parallel), cache, store)
    httpd = make_server(parse_addr(a.addr), a.web, proxy)
    if proxy is not None and not a.no_warm:
        threading.Thread(target=proxy.warm, daemon=True, name="warm-up").start()
    host, port = httpd.server_address[:2]
    mode = "simulation only" if proxy is None else f"IRSA proxy, cache {a.cache}"
    log.info("serving %s on http://%s:%d (%s)", a.web, "localhost" if host in ("", "0.0.0.0") else host, port, mode)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
