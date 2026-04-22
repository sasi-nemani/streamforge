"""
SQS Sidecar Integration Tests with LocalStack.

These tests verify real SQS behavior:
1. VisibilityTimeout=0 truly doesn't hide messages
2. Messages remain in queue after peek
3. Health checks work with real endpoints
4. Multiple peeks return same messages

Run with: pytest tests/integration/test_sqs_integration.py -v
Requires: Docker + pip install streamforge-cli[integration]
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.integration.conftest import requires_docker


@requires_docker
class TestSQSPeekBehavior:
    """Verify peek() truly doesn't consume messages."""

    @pytest.mark.asyncio
    async def test_peek_messages_remain_visible(self, localstack_container, sqs_queue_url):
        """Messages peeked with VisibilityTimeout=0 stay visible."""
        import boto3

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        # Setup: send test messages
        endpoint_url = localstack_container.get_url()
        client = boto3.client(
            "sqs",
            endpoint_url=endpoint_url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        messages = [{"event": "test", "id": i} for i in range(3)]
        for msg in messages:
            client.send_message(QueueUrl=sqs_queue_url, MessageBody=json.dumps(msg))

        # Create sidecar pointing to LocalStack
        config = SQSConfig(
            queue_url=sqs_queue_url,
            region="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Monkey-patch to use LocalStack endpoint
        sidecar = SQSSidecar(config)
        original_get_client = sidecar._get_client

        def patched_get_client():
            if sidecar._client is None:
                sidecar._client = boto3.client(
                    "sqs",
                    endpoint_url=endpoint_url,
                    region_name="us-east-1",
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )
            return sidecar._client

        sidecar._get_client = patched_get_client

        # First peek
        batch1 = await sidecar.peek(max_messages=10)
        assert batch1.message_count == 3, "First peek should see all 3 messages"

        # Second peek should also see all 3 (VisibilityTimeout=0 means no hiding)
        batch2 = await sidecar.peek(max_messages=10)
        assert batch2.message_count == 3, "Second peek should still see all 3 messages"

        # Verify queue depth unchanged
        depth = await sidecar.get_queue_depth()
        assert depth == 3, "Queue depth should remain 3 after peek"

        await sidecar.close()

    @pytest.mark.asyncio
    async def test_peek_receive_count_increments(self, localstack_container, sqs_queue_url):
        """ApproximateReceiveCount increments on each peek (expected SQS behavior)."""
        import boto3

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        endpoint_url = localstack_container.get_url()
        client = boto3.client(
            "sqs",
            endpoint_url=endpoint_url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Send one message
        client.send_message(
            QueueUrl=sqs_queue_url, MessageBody=json.dumps({"test": "receive_count"})
        )

        config = SQSConfig(
            queue_url=sqs_queue_url,
            region="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        sidecar = SQSSidecar(config)

        def patched_get_client():
            if sidecar._client is None:
                sidecar._client = boto3.client(
                    "sqs",
                    endpoint_url=endpoint_url,
                    region_name="us-east-1",
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )
            return sidecar._client

        sidecar._get_client = patched_get_client

        # First peek
        batch1 = await sidecar.peek(max_messages=1)
        count1 = batch1.observations[0].approximate_receive_count

        # Second peek
        batch2 = await sidecar.peek(max_messages=1)
        count2 = batch2.observations[0].approximate_receive_count

        # Receive count should increment
        assert count2 > count1, "ApproximateReceiveCount should increment on peek"

        await sidecar.close()


@requires_docker
class TestSQSHealthCheck:
    """Verify health checks work with real SQS."""

    @pytest.mark.asyncio
    async def test_health_check_succeeds(self, localstack_container, sqs_queue_url):
        """Health check returns success for valid queue."""
        import boto3

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        endpoint_url = localstack_container.get_url()

        config = SQSConfig(
            queue_url=sqs_queue_url,
            region="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        sidecar = SQSSidecar(config)

        def patched_get_client():
            if sidecar._client is None:
                sidecar._client = boto3.client(
                    "sqs",
                    endpoint_url=endpoint_url,
                    region_name="us-east-1",
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )
            return sidecar._client

        sidecar._get_client = patched_get_client

        health = await sidecar.health_check()

        assert health.success is True
        assert health.latency_ms > 0

        await sidecar.close()

    @pytest.mark.asyncio
    async def test_health_check_fails_invalid_queue(self, localstack_container):
        """Health check returns failure for non-existent queue."""
        import boto3

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        endpoint_url = localstack_container.get_url()

        config = SQSConfig(
            queue_url=f"{endpoint_url}/000000000000/nonexistent-queue",
            region="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        sidecar = SQSSidecar(config)

        def patched_get_client():
            if sidecar._client is None:
                sidecar._client = boto3.client(
                    "sqs",
                    endpoint_url=endpoint_url,
                    region_name="us-east-1",
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )
            return sidecar._client

        sidecar._get_client = patched_get_client

        health = await sidecar.health_check()

        assert health.success is False
        assert health.error_message is not None

        await sidecar.close()


@requires_docker
class TestSQSTelemetry:
    """Verify telemetry is emitted during real operations."""

    @pytest.mark.asyncio
    async def test_peek_emits_audit_events(self, localstack_container, sqs_queue_url):
        """Peek operations emit structured audit events."""
        import boto3
        from io import StringIO

        from streamforge.sidecar.models import SQSConfig
        from streamforge.sidecar.sqs import SQSSidecar

        endpoint_url = localstack_container.get_url()
        client = boto3.client(
            "sqs",
            endpoint_url=endpoint_url,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        # Send a message
        client.send_message(
            QueueUrl=sqs_queue_url, MessageBody=json.dumps({"test": "audit"})
        )

        # Capture telemetry
        telemetry_output = StringIO()

        config = SQSConfig(
            queue_url=sqs_queue_url,
            region="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

        sidecar = SQSSidecar(config, telemetry_stream=telemetry_output)

        def patched_get_client():
            if sidecar._client is None:
                sidecar._client = boto3.client(
                    "sqs",
                    endpoint_url=endpoint_url,
                    region_name="us-east-1",
                    aws_access_key_id="test",
                    aws_secret_access_key="test",
                )
            return sidecar._client

        sidecar._get_client = patched_get_client

        await sidecar.peek(max_messages=1)

        # Check telemetry output
        telemetry = telemetry_output.getvalue()
        assert "sidecar_batch_start" in telemetry
        assert "sidecar_batch_complete" in telemetry
        assert "sidecar_operation" in telemetry

        await sidecar.close()
