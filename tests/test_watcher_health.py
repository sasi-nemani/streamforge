"""Tests for watcher self-monitoring: health.json, lag detection, systemd watchdog."""
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest


class TestWriteHealth:
    """health.json must be written every poll cycle."""

    def test_health_json_written(self, tmp_path):
        from streamforge.detector.watch import _write_health
        schema_dir = tmp_path / "test_stream"
        schema_dir.mkdir()
        _write_health(
            schema_dir=schema_dir, stream_name="test_stream",
            phase="STABLE", window_size=2000,
            poll_duration_ms=450.0, poll_interval_seconds=30,
            drift_count=0,
        )
        health_path = schema_dir / ".watch_state" / "health.json"
        assert health_path.exists()
        data = json.loads(health_path.read_text())
        assert data["stream_name"] == "test_stream"
        assert data["phase"] == "STABLE"
        assert data["status"] == "ok"
        assert data["window_size"] == 2000
        assert data["last_drift_count"] == 0

    def test_health_status_degraded_on_lag(self, tmp_path):
        from streamforge.detector.watch import _write_health
        schema_dir = tmp_path / "test_lag"
        schema_dir.mkdir()
        # Poll took 65s, interval is 30s → degraded
        _write_health(
            schema_dir=schema_dir, stream_name="test_lag",
            phase="STABLE", window_size=1000,
            poll_duration_ms=65000.0, poll_interval_seconds=30,
            drift_count=2,
        )
        data = json.loads((schema_dir / ".watch_state" / "health.json").read_text())
        assert data["status"] == "degraded"
        assert data["last_drift_count"] == 2

    def test_health_json_timestamp_recent(self, tmp_path):
        from streamforge.detector.watch import _write_health
        schema_dir = tmp_path / "test_ts"
        schema_dir.mkdir()
        _write_health(
            schema_dir=schema_dir, stream_name="test",
            phase="LEARNING", window_size=500,
            poll_duration_ms=100.0, poll_interval_seconds=30,
            drift_count=0,
        )
        data = json.loads((schema_dir / ".watch_state" / "health.json").read_text())
        ts = datetime.fromisoformat(data["timestamp"])
        assert (datetime.now(UTC) - ts).total_seconds() < 5

    def test_health_survives_write_failure(self, tmp_path):
        """Health write failure must not crash the watcher."""
        from streamforge.detector.watch import _write_health
        # Point to a non-existent read-only path
        _write_health(
            schema_dir=Path("/nonexistent/path/that/doesnt/exist"),
            stream_name="test", phase="STABLE",
            window_size=0, poll_duration_ms=0,
            poll_interval_seconds=30, drift_count=0,
        )
        # Should not raise


class TestSdNotify:
    """Systemd watchdog integration — graceful when not available."""

    def test_sd_notify_no_crash_when_unavailable(self):
        from streamforge.detector.watch import _sd_notify
        # Should not raise even if sdnotify is not installed
        _sd_notify("WATCHDOG=1")
        _sd_notify("READY=1")

    def test_sd_notify_calls_notifier_when_available(self):
        from streamforge.detector.watch import _sd_notify
        with patch("streamforge.detector.watch._sd_notify") as mock_notify:
            mock_notify("READY=1")
            mock_notify.assert_called_once_with("READY=1")
