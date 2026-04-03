"""Serve frontend dist/ and proxy /api to backend."""
import http.server
import urllib.request
import os

BACKEND = "http://127.0.0.1:8001"
DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api"):
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
        req = urllib.request.Request(
            url, data=body, method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(resp.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19487
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on http://0.0.0.0:{port}")
    server.serve_forever()
