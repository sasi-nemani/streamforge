"""Lightweight Prometheus-compatible HTTP metrics server.

Runs in a daemon thread. Serves /metrics (Prometheus text format) and /health (JSON).
Opt-in via STREAMFORGE_METRICS_PORT env var. No external dependencies.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .metrics import prometheus_text

logger = logging.getLogger(__name__)


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/metrics":
            body = prometheus_text().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default stderr logging from BaseHTTPRequestHandler
        pass


class _ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR enabled for fast port recycling."""
    allow_reuse_address = True
    allow_reuse_port = True


class MetricsServer:
    """HTTP server for Prometheus metrics scraping."""

    def __init__(self, port: int = 9090) -> None:
        self._server = _ReusableHTTPServer(("0.0.0.0", port), _MetricsHandler)
        self._thread: threading.Thread | None = None
        self.port = self._server.server_address[1]  # actual port (useful when port=0)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Metrics server started on port %d", self.port)

    def shutdown(self) -> None:
        self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Metrics server stopped")
