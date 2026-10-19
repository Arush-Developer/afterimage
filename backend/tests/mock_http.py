"""A tiny threaded HTTP server for provider tests: routes (method, path-regex) to queued
responses and records every request (path, headers, JSON body)."""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

Response = tuple[int, Any] | Callable[[dict], tuple[int, Any]]


class MockHTTPServer:
    def __init__(self):
        self.routes: list[tuple[str, re.Pattern, list[Response]]] = []
        self.requests: list[dict] = []
        self.delay = 0.0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self, method: str):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    body = raw.decode(errors="replace")
                req = {"method": method, "path": self.path, "headers": dict(self.headers), "body": body}
                outer.requests.append(req)
                if outer.delay:
                    time.sleep(outer.delay)
                status, payload = 404, {"error": "no route"}
                for m, pattern, queue in outer.routes:
                    if m == method and pattern.search(self.path) and queue:
                        item = queue[0] if len(queue) == 1 else queue.pop(0)
                        status, payload = item(req) if callable(item) else item
                        break
                data = json.dumps(payload).encode() if not isinstance(payload, (bytes, str)) else (
                    payload.encode() if isinstance(payload, str) else payload)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client gave up (timeout tests)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def route(self, method: str, path_regex: str, *responses: Response) -> "MockHTTPServer":
        """Queue responses; the last one repeats for any further matching request."""
        self.routes.append((method, re.compile(path_regex), list(responses)))
        return self

    def calls(self, path_regex: str) -> list[dict]:
        return [r for r in self.requests if re.search(path_regex, r["path"])]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "MockHTTPServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
