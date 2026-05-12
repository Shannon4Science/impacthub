"""Serve frontend dist/ and proxy /api to backend."""
import http.server
import os

import httpx

BACKEND = "http://127.0.0.1:8001"
DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

# httpx with no env-derived proxies so we always hit the local backend directly
_HTTPX = httpx.Client(trust_env=False, timeout=httpx.Timeout(connect=5, read=600, write=60, pool=60))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api") or self.path.startswith("/static/"):
            self._proxy()
        else:
            # SPA fallback: serve index.html for non-file paths
            full = os.path.join(DIST, self.path.lstrip("/"))
            if not os.path.exists(full) and not self.path.startswith("/assets"):
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        self._proxy()

    def _proxy(self):
        url = BACKEND + self.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        try:
            with _HTTPX.stream(
                self.command, url, content=body,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            ) as resp:
                self.send_response(resp.status_code)
                content_type = resp.headers.get("content-type", "")
                is_stream = "text/event-stream" in content_type
                self.send_header("Content-Type", content_type or "application/octet-stream")
                if is_stream:
                    self.send_header("Cache-Control", "no-cache, no-transform")
                    self.send_header("X-Accel-Buffering", "no")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    # iter_raw() with no chunk_size yields whatever bytes the
                    # wire delivers — needed so first "thinking" event isn't
                    # buffered while waiting for chunk to fill
                    for chunk in resp.iter_raw():
                        if not chunk:
                            continue
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break
                else:
                    for h in ("Content-Length", "Cache-Control", "ETag"):
                        v = resp.headers.get(h)
                        if v:
                            self.send_header(h, v)
                    self.end_headers()
                    self.wfile.write(resp.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19487
    # ThreadingHTTPServer so a long-running /api/advisor/chat request doesn't
    # block static-asset / parallel-API requests.
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    print(f"Serving on http://0.0.0.0:{port} (threaded)")
    server.serve_forever()
