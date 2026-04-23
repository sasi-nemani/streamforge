"""Tests for Prometheus metrics export and HTTP server."""
import json
import urllib.request
import pytest


class TestPrometheusTextFormat:
    def test_format_contains_help_and_type(self):
        from streamforge.metrics import prometheus_text, _reset_for_testing, POLL_DURATION
        _reset_for_testing()
        POLL_DURATION.observe(1.5)
        text = prometheus_text()
        assert "# HELP poll_duration_seconds" in text
        assert "# TYPE poll_duration_seconds summary" in text
        assert "poll_duration_seconds_count 1" in text

    def test_format_contains_counters(self):
        from streamforge.metrics import prometheus_text, _reset_for_testing, EVENTS_SAMPLED
        _reset_for_testing()
        EVENTS_SAMPLED.inc(500)
        text = prometheus_text()
        assert "# TYPE events_sampled_total counter" in text
        assert "events_sampled_total 500" in text

    def test_format_ends_with_newline(self):
        from streamforge.metrics import prometheus_text
        assert prometheus_text().endswith("\n")


class TestMetricsHttpServer:
    def test_metrics_endpoint(self):
        from streamforge.metrics_server import MetricsServer
        server = MetricsServer(port=0)  # OS picks free port
        server.start()
        try:
            url = f"http://localhost:{server.port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
                body = resp.read().decode()
                assert "poll_duration_seconds" in body
        finally:
            server.shutdown()

    def test_health_endpoint(self):
        from streamforge.metrics_server import MetricsServer
        server = MetricsServer(port=0)
        server.start()
        try:
            url = f"http://localhost:{server.port}/health"
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert resp.status == 200
                data = json.loads(resp.read())
                assert data["status"] == "ok"
        finally:
            server.shutdown()

    def test_shutdown_releases_port(self):
        import time
        from streamforge.metrics_server import MetricsServer
        server = MetricsServer(port=0)
        port = server.port
        server.start()
        server.shutdown()
        time.sleep(0.5)  # allow kernel to release TIME_WAIT
        # Should be able to bind again
        server2 = MetricsServer(port=port)
        server2.start()
        server2.shutdown()

    def test_404_on_unknown_path(self):
        from streamforge.metrics_server import MetricsServer
        server = MetricsServer(port=0)
        server.start()
        try:
            url = f"http://localhost:{server.port}/unknown"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 404
        finally:
            server.shutdown()
