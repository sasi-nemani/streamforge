"""
tests/test_sqs_sidecar.py — TDD Tests for SQS Sidecar Connector
================================================================

Tests for AWS SQS read-only sidecar.

Core principle: NEVER touch or modify messages. NEVER alter queue state.
- Uses ReceiveMessage with VisibilityTimeout=0 (peek, not consume)
- NEVER deletes messages
- NEVER acknowledges messages

Phase 3: SQS Sidecar Connector
"""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestSQSSidecarInit:
    """Tests for SQS sidecar initialization."""

    def test_sidecar_requires_config(self):
        """Sidecar must require valid config."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )
        sidecar = SQSSidecar(config)

        assert sidecar.queue_name == "orders"
        assert sidecar.queue_type == "sqs"

    def test_sidecar_enforces_visibility_timeout_zero(self):
        """Sidecar must enforce VisibilityTimeout=0 in all API calls."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )
        sidecar = SQSSidecar(config)

        # Internal visibility timeout must be 0
        assert sidecar._visibility_timeout == 0


class TestSQSSidecarPeek:
    """Tests for SQS peek (read without consume)."""

    @pytest.mark.asyncio
    async def test_peek_returns_observation_batch(self):
        """Peek must return an ObservationBatch."""
        from streamforge.sidecar.models import ObservationBatch, SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.receive_message.return_value = {
                "Messages": [
                    {
                        "MessageId": "msg-001",
                        "Body": '{"order_id": "123"}',
                        "ReceiptHandle": "receipt-001",
                        "Attributes": {"ApproximateReceiveCount": "1"},
                    }
                ]
            }
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            batch = await sidecar.peek(max_messages=10)

            assert isinstance(batch, ObservationBatch)
            assert batch.message_count == 1
            assert batch.observations[0].message_id == "msg-001"
            assert batch.observations[0].payload == {"order_id": "123"}

    @pytest.mark.asyncio
    async def test_peek_uses_visibility_timeout_zero(self):
        """Peek must use VisibilityTimeout=0 to avoid hiding messages."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.receive_message.return_value = {"Messages": []}
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            await sidecar.peek()

            # Verify VisibilityTimeout=0 was passed
            call_kwargs = mock_sqs.receive_message.call_args[1]
            assert call_kwargs["VisibilityTimeout"] == 0

    @pytest.mark.asyncio
    async def test_peek_never_deletes_messages(self):
        """Peek must NEVER call delete_message."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.receive_message.return_value = {
                "Messages": [{"MessageId": "msg-001", "Body": "{}", "ReceiptHandle": "r1"}]
            }
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            await sidecar.peek()

            # delete_message must NEVER be called
            mock_sqs.delete_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_peek_emits_telemetry(self):
        """Peek must emit telemetry events."""
        from io import StringIO

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        telemetry_output = StringIO()

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.receive_message.return_value = {"Messages": []}
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config, telemetry_stream=telemetry_output)
            await sidecar.peek()

            telemetry_output.seek(0)
            lines = telemetry_output.readlines()
            assert len(lines) >= 1

            event = json.loads(lines[-1])
            assert event["audit"] == "sidecar_operation"
            assert event["operation"] == "peek"


class TestSQSSidecarBrowse:
    """Tests for SQS browse (iterate through queue)."""

    @pytest.mark.asyncio
    async def test_browse_returns_batch_and_cursor(self):
        """Browse must return batch and next cursor."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.receive_message.return_value = {
                "Messages": [{"MessageId": "msg-001", "Body": "{}", "ReceiptHandle": "r1"}]
            }
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            batch, cursor = await sidecar.browse()

            assert batch.message_count == 1
            # SQS doesn't have true cursors, cursor may be None or a marker
            assert cursor is None or isinstance(cursor, str)


class TestSQSSidecarQueueDepth:
    """Tests for queue depth check."""

    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_count(self):
        """get_queue_depth must return approximate message count."""
        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.get_queue_attributes.return_value = {
                "Attributes": {"ApproximateNumberOfMessages": "42"}
            }
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            depth = await sidecar.get_queue_depth()

            assert depth == 42


class TestSQSSidecarHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_verifies_connectivity(self):
        """Health check must verify queue is accessible."""
        from streamforge.sidecar.models import SQSConfig, TelemetryOperation
        from streamforge.sidecar.sqs import SQSSidecar

        config = SQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/orders",
            region="us-east-1",
        )

        with patch("streamforge.sidecar.sqs.SQSSidecar._get_client") as mock_client:
            mock_sqs = MagicMock()
            mock_sqs.get_queue_attributes.return_value = {
                "Attributes": {"ApproximateNumberOfMessages": "10"}
            }
            mock_client.return_value = mock_sqs

            sidecar = SQSSidecar(config)
            result = await sidecar.health_check()

            assert result.operation == TelemetryOperation.HEALTH_CHECK
            assert result.success is True


class TestSQSSidecarSafety:
    """Tests for safety guarantees."""

    def test_sidecar_has_no_delete_method(self):
        """Sidecar must NOT have delete capability."""
        from streamforge.sidecar.sqs import SQSSidecar

        assert not hasattr(SQSSidecar, "delete")
        assert not hasattr(SQSSidecar, "delete_message")

    def test_sidecar_has_no_ack_method(self):
        """Sidecar must NOT have ack capability."""
        from streamforge.sidecar.sqs import SQSSidecar

        assert not hasattr(SQSSidecar, "ack")
        assert not hasattr(SQSSidecar, "acknowledge")

    def test_sidecar_has_no_send_method(self):
        """Sidecar must NOT have send capability."""
        from streamforge.sidecar.sqs import SQSSidecar

        assert not hasattr(SQSSidecar, "send")
        assert not hasattr(SQSSidecar, "send_message")

    def test_sidecar_has_no_purge_method(self):
        """Sidecar must NOT have purge capability."""
        from streamforge.sidecar.sqs import SQSSidecar

        assert not hasattr(SQSSidecar, "purge")
        assert not hasattr(SQSSidecar, "purge_queue")
