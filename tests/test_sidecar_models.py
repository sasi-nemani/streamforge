"""
tests/test_sidecar_models.py — TDD Tests for Queue Sidecar Models
==================================================================

Tests for read-only sidecar observation models.
Core principle: NEVER touch or modify messages. NEVER alter queue state.

Phase 1: Core Models & Protocol
"""

import pytest
from datetime import datetime, UTC
from pydantic import ValidationError


class TestObservationEvent:
    """Tests for the core observation event model."""

    def test_observation_event_has_required_fields(self):
        """Observation must capture what, when, how."""
        from streamforge.sidecar.models import ObservationEvent

        obs = ObservationEvent(
            queue_name="orders-queue",
            message_id="msg-123",
            observed_at=datetime.now(UTC),
            payload={"order_id": "12345"},
            observation_method="peek",
        )

        assert obs.queue_name == "orders-queue"
        assert obs.message_id == "msg-123"
        assert obs.payload == {"order_id": "12345"}
        assert obs.observation_method == "peek"
        assert obs.observed_at is not None

    def test_observation_event_is_immutable(self):
        """Observations must be immutable — no post-hoc tampering."""
        from streamforge.sidecar.models import ObservationEvent

        obs = ObservationEvent(
            queue_name="orders-queue",
            message_id="msg-123",
            observed_at=datetime.now(UTC),
            payload={"order_id": "12345"},
            observation_method="peek",
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            obs.queue_name = "tampered"

    def test_observation_event_captures_metadata(self):
        """Observations must include queue-specific metadata."""
        from streamforge.sidecar.models import ObservationEvent

        obs = ObservationEvent(
            queue_name="orders-queue",
            message_id="msg-123",
            observed_at=datetime.now(UTC),
            payload={"order_id": "12345"},
            observation_method="browse",
            queue_type="ibm_mq",
            approximate_receive_count=3,
            message_attributes={"Priority": "high"},
        )

        assert obs.queue_type == "ibm_mq"
        assert obs.approximate_receive_count == 3
        assert obs.message_attributes == {"Priority": "high"}


class TestTelemetryEvent:
    """Tests for telemetry/audit events."""

    def test_telemetry_event_captures_operation(self):
        """Telemetry must record what operation was performed."""
        from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation

        event = TelemetryEvent(
            operation=TelemetryOperation.PEEK,
            queue_name="payments-queue",
            timestamp=datetime.now(UTC),
            success=True,
            messages_observed=10,
            latency_ms=45.2,
        )

        assert event.operation == TelemetryOperation.PEEK
        assert event.success is True
        assert event.messages_observed == 10

    def test_telemetry_event_captures_failures(self):
        """Telemetry must capture failure details for debugging."""
        from streamforge.sidecar.models import TelemetryEvent, TelemetryOperation

        event = TelemetryEvent(
            operation=TelemetryOperation.PEEK,
            queue_name="payments-queue",
            timestamp=datetime.now(UTC),
            success=False,
            messages_observed=0,
            latency_ms=1200.5,
            error_code="AccessDenied",
            error_message="Queue access denied",
        )

        assert event.success is False
        assert event.error_code == "AccessDenied"
        assert event.error_message == "Queue access denied"

    def test_telemetry_operations_are_read_only(self):
        """Only read-only operations allowed — no consume, delete, ack."""
        from streamforge.sidecar.models import TelemetryOperation

        read_only_ops = {TelemetryOperation.PEEK, TelemetryOperation.BROWSE,
                         TelemetryOperation.COUNT, TelemetryOperation.HEALTH_CHECK}

        # These should NOT exist
        assert not hasattr(TelemetryOperation, "CONSUME")
        assert not hasattr(TelemetryOperation, "DELETE")
        assert not hasattr(TelemetryOperation, "ACK")
        assert not hasattr(TelemetryOperation, "PURGE")


class TestSidecarProtocol:
    """Tests for the read-only sidecar protocol."""

    def test_protocol_defines_peek_method(self):
        """Protocol must define peek (non-destructive read)."""
        from streamforge.sidecar.protocol import QueueSidecar

        # Protocol must have peek method
        assert hasattr(QueueSidecar, "peek")

    def test_protocol_defines_browse_method(self):
        """Protocol must define browse (iterate without consuming)."""
        from streamforge.sidecar.protocol import QueueSidecar

        assert hasattr(QueueSidecar, "browse")

    def test_protocol_defines_queue_depth(self):
        """Protocol must define queue depth check."""
        from streamforge.sidecar.protocol import QueueSidecar

        assert hasattr(QueueSidecar, "get_queue_depth")

    def test_protocol_has_no_destructive_methods(self):
        """Protocol must NOT have any destructive methods."""
        from streamforge.sidecar.protocol import QueueSidecar

        # These must NOT exist on the protocol
        assert not hasattr(QueueSidecar, "consume")
        assert not hasattr(QueueSidecar, "delete")
        assert not hasattr(QueueSidecar, "ack")
        assert not hasattr(QueueSidecar, "purge")
        assert not hasattr(QueueSidecar, "send")
        assert not hasattr(QueueSidecar, "commit")

    def test_protocol_is_runtime_checkable(self):
        """Protocol must be runtime checkable for duck typing."""
        from streamforge.sidecar.protocol import QueueSidecar
        from typing import runtime_checkable, Protocol

        # Should be decorated with @runtime_checkable
        assert hasattr(QueueSidecar, "__protocol_attrs__") or \
               getattr(QueueSidecar, "_is_runtime_protocol", False)


class TestQueueConfig:
    """Tests for queue configuration models."""

    def test_sqs_config_validation(self):
        """SQS config must require region and queue URL."""
        from streamforge.sidecar.models import SQSConfig

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        assert config.queue_url.startswith("https://sqs")
        assert config.region == "us-east-1"
        # Default visibility timeout for peek must be 0
        assert config.visibility_timeout_seconds == 0

    def test_ibm_mq_config_validation(self):
        """IBM MQ config must require host, port, queue manager, queue name."""
        from streamforge.sidecar.models import IBMMQConfig

        config = IBMMQConfig(
            host="mq.company.com",
            port=1414,
            queue_manager="QM1",
            queue_name="DEV.QUEUE.1",
            channel="DEV.APP.SVRCONN",
        )

        assert config.host == "mq.company.com"
        assert config.port == 1414
        assert config.queue_manager == "QM1"
        # Browse mode must be default
        assert config.browse_mode is True

    def test_config_rejects_destructive_settings(self):
        """Config must not allow settings that would alter queue state."""
        from streamforge.sidecar.models import SQSConfig
        from pydantic import ValidationError

        # Attempting to set visibility timeout > 0 should fail or warn
        # because it would hide messages from other consumers
        with pytest.raises(ValidationError):
            SQSConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
                region="us-east-1",
                visibility_timeout_seconds=30,  # NOT ALLOWED
            )


class TestObservationBatch:
    """Tests for batched observations."""

    def test_batch_tracks_statistics(self):
        """Batch must track observation statistics."""
        from streamforge.sidecar.models import ObservationBatch, ObservationEvent
        from datetime import datetime, UTC

        events = [
            ObservationEvent(
                queue_name="orders",
                message_id=f"msg-{i}",
                observed_at=datetime.now(UTC),
                payload={"i": i},
                observation_method="peek",
            )
            for i in range(5)
        ]

        batch = ObservationBatch(
            queue_name="orders",
            observations=events,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

        assert batch.message_count == 5
        assert batch.queue_name == "orders"

    def test_batch_is_immutable(self):
        """Batch must be immutable after creation."""
        from streamforge.sidecar.models import ObservationBatch
        from datetime import datetime, UTC

        batch = ObservationBatch(
            queue_name="orders",
            observations=[],
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            batch.observations.append("tampered")
