"""Tests for operational hardening: health wiring, dead code removal, Prometheus metrics.

RED phase — these tests must fail before implementation, pass after.
"""
import json

# ═══════════════════════════════════════════════════════════════════════════════
# Item 1: _write_health() must be called from watch loops
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthWiredIntoPollLoops:
    """_write_health must be called from both watch_stream and _watch_kafka_async."""

    def test_write_health_called_in_file_watch_loop(self):
        """Verify _write_health is referenced in watch_stream function body."""
        import inspect

        from streamforge.detector.watch import watch_stream
        source = inspect.getsource(watch_stream)
        assert "_write_health(" in source, \
            "_write_health() must be called inside watch_stream()"

    def test_write_health_called_in_kafka_watch_loop(self):
        """Verify _write_health is referenced in _watch_kafka_async function body."""
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "_write_health(" in source, \
            "_write_health() must be called inside _watch_kafka_async()"

    def test_sd_notify_called_in_kafka_watch_loop(self):
        """Verify _sd_notify is referenced in _watch_kafka_async function body."""
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "_sd_notify(" in source, \
            "_sd_notify() must be called inside _watch_kafka_async()"


# ═══════════════════════════════════════════════════════════════════════════════
# Item 2: _is_retryable() — remove dead code or wire it in
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoDeadCode:
    """No dead code in production files."""

    def test_is_retryable_used_in_kafka_connector(self):
        """_is_retryable must be called somewhere in kafka.py, or removed."""
        import inspect

        import streamforge.connectors.kafka as kafka_mod
        # Get all function/method source code in the module
        module_source = inspect.getsource(kafka_mod)
        # _is_retryable should either be called in production code or not exist
        if hasattr(kafka_mod, "_is_retryable"):
            # If it exists, it must be called (not just defined)
            # Count occurrences: definition is 1, calls add more
            count = module_source.count("_is_retryable")
            assert count >= 2, \
                "_is_retryable is defined but never called — dead code"


# ═══════════════════════════════════════════════════════════════════════════════
# Item 4: Prometheus-style metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherMetrics:
    """Watcher must export Prometheus-compatible metrics."""

    def test_metrics_module_exists(self):
        from streamforge import metrics
        assert hasattr(metrics, "POLL_DURATION")
        assert hasattr(metrics, "EVENTS_SAMPLED")
        assert hasattr(metrics, "DRIFT_DETECTED")

    def test_poll_duration_tracks_timing(self):
        from streamforge.metrics import POLL_DURATION
        POLL_DURATION.observe(0.45)
        POLL_DURATION.observe(0.52)
        assert POLL_DURATION.count >= 2
        assert POLL_DURATION.total >= 0.9

    def test_events_sampled_increments(self):
        from streamforge.metrics import EVENTS_SAMPLED
        before = EVENTS_SAMPLED.value
        EVENTS_SAMPLED.inc(500)
        assert EVENTS_SAMPLED.value == before + 500

    def test_drift_detected_increments(self):
        from streamforge.metrics import DRIFT_DETECTED
        before = DRIFT_DETECTED.value
        DRIFT_DETECTED.inc()
        assert DRIFT_DETECTED.value == before + 1

    def test_metrics_to_dict(self):
        """Metrics must be exportable as a dict for health.json integration."""
        from streamforge.metrics import metrics_snapshot
        snapshot = metrics_snapshot()
        assert "poll_duration_seconds_count" in snapshot
        assert "events_sampled_total" in snapshot
        assert "drift_detected_total" in snapshot

    def test_health_json_includes_metrics(self, tmp_path):
        """_write_health must include metrics in the output."""
        from streamforge.detector.watch import _write_health
        schema_dir = tmp_path / "test"
        schema_dir.mkdir()
        _write_health(
            schema_dir=schema_dir, stream_name="test",
            phase="STABLE", window_size=2000,
            poll_duration_ms=450.0, poll_interval_seconds=30,
            drift_count=0,
        )
        data = json.loads((schema_dir / ".watch_state" / "health.json").read_text())
        # Metrics fields should be present
        assert "metrics" in data
        assert "poll_duration_seconds_count" in data["metrics"]


class TestWatchImports:
    """Critical imports must be present — missing _time crashed file-based watch."""

    def test_time_module_imported(self):
        """watch.py must import time as _time for poll timing."""
        import streamforge.detector.watch as watch_mod
        assert hasattr(watch_mod, "_time"), "Missing 'import time as _time' in watch.py"
        assert watch_mod._time.monotonic is not None


class TestKafkaLoopTimingAndMetrics:
    """Kafka loop must measure poll timing and increment metrics in ALL phases."""

    def test_kafka_loop_has_kpoll_start_timing(self):
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "_kpoll_start = _time.monotonic()" in source, \
            "Kafka loop must record poll start time"

    def test_kafka_loop_learning_has_poll_duration(self):
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "_kpoll_ms = (_time.monotonic() - _kpoll_start)" in source, \
            "Kafka loop must calculate poll duration in ms"

    def test_kafka_loop_has_no_hardcoded_zero_duration(self):
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "poll_duration_ms=0" not in source, \
            "Kafka loop must use actual poll_duration_ms, not hardcoded 0"

    def test_kafka_loop_increments_poll_duration_metric(self):
        import inspect

        from streamforge.detector.watch import _watch_kafka_async
        source = inspect.getsource(_watch_kafka_async)
        assert "POLL_DURATION.observe(" in source, \
            "Kafka loop must call POLL_DURATION.observe()"


class TestMetricsWiredIntoWatchLoops:
    """Metric counters must be incremented in the actual poll loop code."""

    def test_metrics_import_in_watch_module(self):
        """watch.py must import metrics for counter increments."""
        import inspect

        from streamforge.detector import watch as watch_mod
        source = inspect.getsource(watch_mod)
        assert "POLL_CYCLES" in source, "POLL_CYCLES counter must be used in watch.py"
        assert "EVENTS_SAMPLED" in source, "EVENTS_SAMPLED counter must be used in watch.py"
        assert "DRIFT_DETECTED" in source, "DRIFT_DETECTED counter must be used in watch.py"
        assert "POLL_DURATION" in source, "POLL_DURATION summary must be used in watch.py"

    def test_metrics_increment_on_observe(self):
        """Verify metrics are functional after import in watch module."""
        from streamforge.metrics import (
            DRIFT_DETECTED,
            EVENTS_SAMPLED,
            POLL_CYCLES,
            POLL_DURATION,
        )
        # Record baseline
        c_before = POLL_CYCLES.value
        e_before = EVENTS_SAMPLED.value
        d_before = DRIFT_DETECTED.value
        p_before = POLL_DURATION.count

        POLL_CYCLES.inc()
        EVENTS_SAMPLED.inc(500)
        DRIFT_DETECTED.inc(3)
        POLL_DURATION.observe(0.45)

        assert POLL_CYCLES.value == c_before + 1
        assert EVENTS_SAMPLED.value == e_before + 500
        assert DRIFT_DETECTED.value == d_before + 3
        assert POLL_DURATION.count == p_before + 1
