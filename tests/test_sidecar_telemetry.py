"""
tests/test_sidecar_telemetry.py — TDD Tests for Sidecar Telemetry
==================================================================

Tests for audit trail and telemetry infrastructure.
Every sidecar operation must be fully auditable with:
- WHAT: operation performed
- WHEN: timestamp
- HOW: method, parameters, result

Phase 2: Telemetry Infrastructure
"""

import pytest
import json
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock
from io import StringIO


class TestSidecarAudit:
    """Tests for sidecar audit logging."""

    def test_audit_emits_structured_json(self):
        """Audit events must be structured JSON for machine parsing."""
        from streamforge.sidecar.telemetry import SidecarAudit
        from streamforge.sidecar.models import TelemetryOperation

        output = StringIO()
        audit = SidecarAudit(output_stream=output)

        audit.log_operation(
            operation=TelemetryOperation.PEEK,
            queue_name="orders-queue",
            success=True,
            messages_observed=5,
            latency_ms=42.5,
        )

        output.seek(0)
        line = output.readline()
        event = json.loads(line)

        assert event["audit"] == "sidecar_operation"
        assert event["operation"] == "peek"
        assert event["queue_name"] == "orders-queue"
        assert event["success"] is True
        assert event["messages_observed"] == 5
        assert event["latency_ms"] == 42.5
        assert "ts" in event

    def test_audit_captures_failures(self):
        """Audit must capture error details for debugging."""
        from streamforge.sidecar.telemetry import SidecarAudit
        from streamforge.sidecar.models import TelemetryOperation

        output = StringIO()
        audit = SidecarAudit(output_stream=output)

        audit.log_operation(
            operation=TelemetryOperation.PEEK,
            queue_name="orders-queue",
            success=False,
            messages_observed=0,
            latency_ms=1500.0,
            error_code="AccessDenied",
            error_message="No permission to read queue",
        )

        output.seek(0)
        event = json.loads(output.readline())

        assert event["success"] is False
        assert event["error_code"] == "AccessDenied"
        assert event["error_message"] == "No permission to read queue"

    def test_audit_captures_what_when_how(self):
        """Every audit event must answer: what, when, how."""
        from streamforge.sidecar.telemetry import SidecarAudit
        from streamforge.sidecar.models import TelemetryOperation

        output = StringIO()
        audit = SidecarAudit(output_stream=output)

        audit.log_observation(
            queue_name="payments-queue",
            message_id="msg-abc123",
            observation_method="browse",
            payload_size_bytes=1024,
        )

        output.seek(0)
        event = json.loads(output.readline())

        # WHAT
        assert event["audit"] == "sidecar_observation"
        assert event["queue_name"] == "payments-queue"
        assert event["message_id"] == "msg-abc123"

        # WHEN
        assert "ts" in event

        # HOW
        assert event["observation_method"] == "browse"

    def test_audit_log_batch_start(self):
        """Audit must log batch start for correlation."""
        from streamforge.sidecar.telemetry import SidecarAudit

        output = StringIO()
        audit = SidecarAudit(output_stream=output)

        audit.log_batch_start(
            batch_id="batch-001",
            queue_name="orders-queue",
            max_messages=10,
        )

        output.seek(0)
        event = json.loads(output.readline())

        assert event["audit"] == "sidecar_batch_start"
        assert event["batch_id"] == "batch-001"
        assert event["queue_name"] == "orders-queue"
        assert event["max_messages"] == 10

    def test_audit_log_batch_complete(self):
        """Audit must log batch completion with statistics."""
        from streamforge.sidecar.telemetry import SidecarAudit

        output = StringIO()
        audit = SidecarAudit(output_stream=output)

        audit.log_batch_complete(
            batch_id="batch-001",
            queue_name="orders-queue",
            messages_observed=7,
            duration_ms=125.5,
            success=True,
        )

        output.seek(0)
        event = json.loads(output.readline())

        assert event["audit"] == "sidecar_batch_complete"
        assert event["batch_id"] == "batch-001"
        assert event["messages_observed"] == 7
        assert event["duration_ms"] == 125.5

    def test_audit_is_thread_safe(self):
        """Audit must be safe for concurrent writes."""
        from streamforge.sidecar.telemetry import SidecarAudit
        from streamforge.sidecar.models import TelemetryOperation
        import threading

        output = StringIO()
        audit = SidecarAudit(output_stream=output)
        errors = []

        def log_many():
            try:
                for i in range(100):
                    audit.log_operation(
                        operation=TelemetryOperation.PEEK,
                        queue_name=f"queue-{threading.current_thread().name}",
                        success=True,
                        messages_observed=i,
                        latency_ms=1.0,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=log_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        output.seek(0)
        lines = output.readlines()
        assert len(lines) == 500  # 5 threads * 100 logs


class TestMetricsCollector:
    """Tests for metrics collection."""

    def test_metrics_tracks_operation_count(self):
        """Metrics must count operations by type."""
        from streamforge.sidecar.telemetry import MetricsCollector
        from streamforge.sidecar.models import TelemetryOperation

        metrics = MetricsCollector()

        metrics.record_operation(TelemetryOperation.PEEK, success=True)
        metrics.record_operation(TelemetryOperation.PEEK, success=True)
        metrics.record_operation(TelemetryOperation.BROWSE, success=True)
        metrics.record_operation(TelemetryOperation.PEEK, success=False)

        stats = metrics.get_stats()
        assert stats["operations"]["peek"]["total"] == 3
        assert stats["operations"]["peek"]["success"] == 2
        assert stats["operations"]["peek"]["failure"] == 1
        assert stats["operations"]["browse"]["total"] == 1

    def test_metrics_tracks_latency_histogram(self):
        """Metrics must track latency distribution."""
        from streamforge.sidecar.telemetry import MetricsCollector
        from streamforge.sidecar.models import TelemetryOperation

        metrics = MetricsCollector()

        metrics.record_latency(TelemetryOperation.PEEK, 10.0)
        metrics.record_latency(TelemetryOperation.PEEK, 20.0)
        metrics.record_latency(TelemetryOperation.PEEK, 30.0)

        stats = metrics.get_stats()
        assert stats["latency"]["peek"]["count"] == 3
        assert stats["latency"]["peek"]["avg"] == 20.0
        assert stats["latency"]["peek"]["min"] == 10.0
        assert stats["latency"]["peek"]["max"] == 30.0

    def test_metrics_tracks_messages_observed(self):
        """Metrics must track total messages observed."""
        from streamforge.sidecar.telemetry import MetricsCollector

        metrics = MetricsCollector()

        metrics.record_messages_observed("orders-queue", 10)
        metrics.record_messages_observed("orders-queue", 5)
        metrics.record_messages_observed("payments-queue", 20)

        stats = metrics.get_stats()
        assert stats["queues"]["orders-queue"]["total_observed"] == 15
        assert stats["queues"]["payments-queue"]["total_observed"] == 20

    def test_metrics_exports_prometheus_format(self):
        """Metrics must export in Prometheus format."""
        from streamforge.sidecar.telemetry import MetricsCollector
        from streamforge.sidecar.models import TelemetryOperation

        metrics = MetricsCollector()
        metrics.record_operation(TelemetryOperation.PEEK, success=True)
        metrics.record_latency(TelemetryOperation.PEEK, 15.0)
        metrics.record_messages_observed("orders", 10)

        prometheus = metrics.export_prometheus()

        assert "streamforge_sidecar_operations_total" in prometheus
        assert "streamforge_sidecar_latency_ms" in prometheus
        assert "streamforge_sidecar_messages_observed_total" in prometheus


class TestTelemetryContext:
    """Tests for telemetry context management."""

    def test_context_provides_timing(self):
        """Context manager must provide automatic timing."""
        from streamforge.sidecar.telemetry import telemetry_context
        from streamforge.sidecar.models import TelemetryOperation
        import time

        with telemetry_context(TelemetryOperation.PEEK, "test-queue") as ctx:
            time.sleep(0.01)  # 10ms

        assert ctx.latency_ms >= 10.0
        assert ctx.operation == TelemetryOperation.PEEK
        assert ctx.queue_name == "test-queue"

    def test_context_captures_exceptions(self):
        """Context must capture exception details."""
        from streamforge.sidecar.telemetry import telemetry_context
        from streamforge.sidecar.models import TelemetryOperation

        ctx = None
        with pytest.raises(ValueError):
            with telemetry_context(TelemetryOperation.PEEK, "test-queue") as ctx:
                raise ValueError("Test error")

        assert ctx.success is False
        assert ctx.error_message == "Test error"

    def test_context_marks_success(self):
        """Context must mark success when no exception."""
        from streamforge.sidecar.telemetry import telemetry_context
        from streamforge.sidecar.models import TelemetryOperation

        with telemetry_context(TelemetryOperation.PEEK, "test-queue") as ctx:
            ctx.messages_observed = 5

        assert ctx.success is True
        assert ctx.messages_observed == 5
