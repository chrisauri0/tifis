import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest


class FakeServer:
    """A local HTTP server whose answers come from a Python function:
    handler(path, query, headers) -> (status, body bytes, extra headers)."""

    def __init__(self, handler):
        outer = self
        self.calls = []

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                u = urlsplit(self.path)
                q = parse_qs(u.query, keep_blank_values=True)
                outer.calls.append((u.path, q, dict(self.headers)))
                status, body, extra = handler(u.path, q, self.headers)
                self.send_response(status)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def calls_to(self, prefix: str):
        return [c for c in self.calls if c[0].startswith(prefix)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_server():
    servers = []

    def make(handler):
        s = FakeServer(handler)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def serve_range(data: bytes, headers):
    """206 answer for a 'Range: bytes=a-b' request, or the whole file."""
    r = headers.get("Range")
    if not r:
        return 200, data, {}
    lo, hi = r.removeprefix("bytes=").split("-")
    lo, hi = int(lo), min(int(hi), len(data) - 1)
    return 206, data[lo : hi + 1], {"Content-Range": f"bytes {lo}-{hi}/{len(data)}"}
