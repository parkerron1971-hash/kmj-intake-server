"""Loopback-only demo HTTP API, not a production server or an auth boundary."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlparse

from .engine import demo_context

MAX_BODY = 8192


def make_server(engine, port=8766):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Customer text is never logged.

        def _json(self, status, value):
            encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def _local(self):
            try:
                host = urlparse("http://" + self.headers.get("Host", "")).hostname
            except ValueError:
                return False
            return host in ("127.0.0.1", "localhost") and not self.headers.get("Origin")

        def do_GET(self):
            if not self._local():
                return self._json(403, {"error": "Loopback demo only"})
            if self.path != "/health":
                return self._json(404, {"error": "Use POST /decide"})
            self._json(200, {"ready": True, "mode": "fictional_local_demo", "paid_calls": 0})

        def do_POST(self):
            if not self._local():
                return self._json(403, {"error": "Loopback demo only"})
            if self.path != "/decide":
                return self._json(404, {"error": "Not found"})
            if self.headers.get_content_type() != "application/json":
                return self._json(415, {"error": "Send application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"error": "Invalid content length"})
            if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY:
                return self._json(413, {"error": "Body must be 1-8192 bytes"})
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) - {"message", "business_id"}:
                    raise ValueError("Use message and optional business_id; demo facts are server-owned")
                business_id = data.get("business_id", "demo-salon")
                out = engine.decide(data.get("message"), business_id=business_id,
                                    context=demo_context(business_id))
                self._json(200, out)
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                self._json(400, {"error": str(exc)})

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 64

        def get_request(self):
            sock, addr = super().get_request()
            sock.settimeout(5)
            return sock, addr

    return LocalServer(("127.0.0.1", port), Handler)
