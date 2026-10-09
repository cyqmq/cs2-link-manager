"""Tests for daemon readiness probing (Bug 1: nonce verification)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cs2lm.daemon import _probe_ready


class _HealthHandler(BaseHTTPRequestHandler):
    nonce: str | None = None

    def do_GET(self):  # noqa: N802
        if self.path != "/api/health":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"status": "ok", "nonce": self.nonce}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        pass


def _start_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    _HealthHandler.nonce = "launch-nonce-abc"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_probe_ready_requires_matching_nonce():
    """An already-running daemon on the port must not satisfy our probe."""
    server, thread = _start_server()
    try:
        port = server.server_address[1]
        # Matching nonce -> this is our child.
        assert _probe_ready("127.0.0.1", port, None, nonce="launch-nonce-abc") is True
        # Different nonce (another daemon owns the port) -> not ready.
        assert _probe_ready("127.0.0.1", port, None, nonce="other-nonce") is False
        # No nonce requested (legacy / non-daemon callers) -> healthy is enough.
        assert _probe_ready("127.0.0.1", port, None) is True
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()