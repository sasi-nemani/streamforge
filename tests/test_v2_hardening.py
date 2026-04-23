"""V2 hardening tests: source factory, namespace wiring, audit sampling,
supervisor HA, and event-driven watch integration.

Targets the 5 remaining gaps from the Netflix review.
"""
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from streamforge.metrics import _reset_for_testing, POLL_CYCLES, EVENTS_SAMPLED


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 1: Source-agnostic factory pattern (replaces string-based Kafka dispatch)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSourceFactory:
    """URI-based dispatch must use a registry, not string matching."""

    def test_resolve_file_uri(self):
        from streamforge.connectors.factory import resolve_stream_source
        source_type, parsed = resolve_stream_source("events/payments")
        assert source_type == "file"
        assert parsed == "events/payments"

    def test_resolve_kafka_uri(self):
        from streamforge.connectors.factory import resolve_stream_source
        source_type, parsed = resolve_stream_source("kafka://events.payments")
        assert source_type == "kafka"
        assert parsed == "events.payments"

    def test_resolve_unknown_scheme_raises(self):
        from streamforge.connectors.factory import resolve_stream_source
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_stream_source("ftp://something")

    def test_supervisor_uses_factory(self):
        """supervisor._worker_main must use resolve_stream_source, not hardcoded string check."""
        import inspect
        from streamforge.supervisor import _worker_main
        source = inspect.getsource(_worker_main)
        assert "resolve_stream_source" in source, \
            "supervisor must use factory, not is_kafka string check"
        assert 'startswith("kafka://")' not in source, \
            "supervisor must not use hardcoded kafka:// string check"


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 2: Namespace wired into actual paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestNamespaceWiredIntoPaths:
    """Namespace must actually prefix schema and drift report paths."""

    def test_resolve_path_with_namespace(self):
        from streamforge.config import Config
        cfg = Config(namespace="team-payments")
        result = cfg.resolve_path("schemas")
        assert "team-payments" in str(result)

    def test_resolve_path_default_no_prefix(self):
        from streamforge.config import Config
        cfg = Config()  # default namespace
        result = cfg.resolve_path("schemas")
        assert str(result) == "schemas"

    def test_resolve_path_sanitizes_slug(self):
        from streamforge.config import Config
        cfg = Config(namespace="Team #1!")
        result = cfg.resolve_path("schemas")
        assert "#" not in str(result)
        assert "!" not in str(result)


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 3: Audit log sampling (reduce volume at scale)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditSampling:
    """Heartbeat logs must be sampled to reduce volume at scale."""

    def test_heartbeat_sampling_every_nth(self, monkeypatch):
        """With STREAMFORGE_AUDIT_HEARTBEAT_EVERY=10, only every 10th heartbeat logs."""
        import streamforge.audit as audit_mod
        monkeypatch.setenv("STREAMFORGE_AUDIT_HEARTBEAT_EVERY", "10")

        # Reset the counter
        audit_mod._heartbeat_counter = 0

        logged = []
        original_log = audit_mod._audit_logger.log

        def capture(level, msg, *args, **kwargs):
            logged.append(msg)

        audit_mod._audit_logger.log = capture
        audit_mod._configured = True
        audit_mod._audit_logger.setLevel(logging.DEBUG)

        try:
            for i in range(25):
                audit_mod.log_poll_heartbeat(
                    stream="test", events_sampled=500,
                    window_size=2000, drift_count=0,
                )
            # With every=10, should log on cycles 0, 10, 20 = 3 logs
            heartbeat_logs = [l for l in logged if "poll_heartbeat" in l]
            assert len(heartbeat_logs) <= 5, \
                f"Expected ~3 heartbeat logs with every=10, got {len(heartbeat_logs)}"
        finally:
            audit_mod._audit_logger.log = original_log

    def test_drift_events_always_logged(self, monkeypatch):
        """Drift events must NEVER be sampled — always log."""
        import streamforge.audit as audit_mod
        monkeypatch.setenv("STREAMFORGE_AUDIT_HEARTBEAT_EVERY", "1000")

        logged = []
        original_log = audit_mod._audit_logger.log

        def capture(level, msg, *args, **kwargs):
            logged.append(msg)

        audit_mod._audit_logger.log = capture
        audit_mod._configured = True
        audit_mod._audit_logger.setLevel(logging.DEBUG)

        try:
            for i in range(5):
                audit_mod.log_drift_check(
                    field_path="amount", check_type="presence",
                    verdict="drift", stream="test",
                )
            drift_logs = [l for l in logged if "drift_check" in l]
            assert len(drift_logs) == 5, "Drift events must always be logged"
        finally:
            audit_mod._audit_logger.log = original_log


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 4: Supervisor HA — PID file + systemd integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupervisorHA:
    """Supervisor must write PID file and support systemd Type=notify."""

    def test_supervisor_writes_pid_file(self, tmp_path):
        from streamforge.supervisor import Supervisor
        from streamforge.models import SupervisorConfig, StreamAssignment
        cfg = SupervisorConfig(
            assignments=[],  # no workers — just test PID file
            pid_file=str(tmp_path / "supervisor.pid"),
        )
        sup = Supervisor(cfg)
        sup._write_pid_file()
        pid_path = Path(cfg.pid_file)
        assert pid_path.exists()
        assert int(pid_path.read_text().strip()) == os.getpid()

    def test_supervisor_cleans_pid_on_shutdown(self, tmp_path):
        from streamforge.supervisor import Supervisor
        from streamforge.models import SupervisorConfig
        cfg = SupervisorConfig(
            assignments=[],
            pid_file=str(tmp_path / "supervisor.pid"),
        )
        sup = Supervisor(cfg)
        sup._write_pid_file()
        sup._remove_pid_file()
        assert not Path(cfg.pid_file).exists()

    def test_supervisor_detects_stale_pid(self, tmp_path):
        """If PID file exists with a dead PID, supervisor should start anyway."""
        from streamforge.supervisor import Supervisor
        from streamforge.models import SupervisorConfig
        pid_path = tmp_path / "supervisor.pid"
        pid_path.write_text("99999999")  # dead PID
        cfg = SupervisorConfig(
            assignments=[],
            pid_file=str(pid_path),
        )
        sup = Supervisor(cfg)
        # Should not raise — stale PID file should be overwritten
        sup._write_pid_file()
        assert int(pid_path.read_text().strip()) == os.getpid()


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 5: Event-driven watch integration tests (replace time.sleep)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_schema(stream_name: str = "test_stream"):
    from streamforge.models import FieldSchema, FieldType, InferredSchema
    return InferredSchema(
        stream_name=stream_name, version="1.0.0",
        inferred_at="2026-04-04T10:00:00Z", event_count_sampled=100,
        fields=[
            FieldSchema(name="event_type", path="event_type", field_type=FieldType.STRING,
                        required=True, presence_rate=1.0, confidence=0.95),
            FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                        required=True, presence_rate=1.0, confidence=0.95),
        ],
        inference_model="test", inference_confidence=0.95,
    )


def _write_events(folder: Path, count: int = 50) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "events.ndjson", "w") as f:
        for i in range(count):
            f.write(json.dumps({"event_type": "purchase", "amount": 99.99 + i}) + "\n")


class TestEventDrivenWatchIntegration:
    """Watch loop integration using event-driven sync instead of time.sleep."""

    def test_poll_cycle_with_event_sync(self, tmp_path):
        """Use POLL_CYCLES counter as sync signal instead of time.sleep."""
        _reset_for_testing()

        events_dir = tmp_path / "events"
        _write_events(events_dir, count=60)
        schemas_dir = tmp_path / "schemas"
        stream_dir = schemas_dir / "test_stream"
        stream_dir.mkdir(parents=True)

        schema = _make_schema()
        from streamforge.schema_writer import write_schema
        write_schema(schema, str(schemas_dir))

        from streamforge.detector.watch import _shutdown

        def run_watch():
            from streamforge.detector.watch import watch_stream
            with patch("signal.signal", return_value=signal.SIG_DFL):
                watch_stream(
                    stream_path=str(events_dir),
                    schema_path=str(stream_dir / "schema.yaml"),
                    poll_interval_seconds=1,
                    sample_size=30,
                    window_capacity=200,
                )

        _shutdown.clear()
        t = threading.Thread(target=run_watch, daemon=True)
        t.start()

        # Event-driven: wait for POLL_CYCLES to reach 2 (instead of time.sleep)
        deadline = time.monotonic() + 10  # 10s max
        while POLL_CYCLES.value < 2 and time.monotonic() < deadline:
            time.sleep(0.1)

        _shutdown.set()
        t.join(timeout=5)

        assert POLL_CYCLES.value >= 2, f"Expected >=2 cycles, got {POLL_CYCLES.value}"

        # Verify artifacts exist
        watch_state = stream_dir / ".watch_state"
        assert (watch_state / "health.json").exists()
        assert (watch_state / "window.ndjson").exists()
