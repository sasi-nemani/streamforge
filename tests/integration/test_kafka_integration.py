"""
Kafka Connector Integration Tests with Testcontainers.

These tests verify real Kafka behavior:
1. read_batch returns parsed JSON events
2. ack commits offsets correctly
3. Partition assignment works
4. Error handling with real broker

Run with: pytest tests/integration/test_kafka_integration.py -v
Requires: Docker + pip install streamforge-cli[integration,kafka]
"""

from __future__ import annotations

import json
import time

import pytest

from tests.integration.conftest import requires_docker


@requires_docker
class TestKafkaReadBatch:
    """Verify read_batch works with real Kafka."""

    @pytest.mark.asyncio
    async def test_read_batch_returns_parsed_events(
        self, kafka_container, kafka_bootstrap_servers, kafka_topic
    ):
        """read_batch returns properly parsed JSON events."""
        from kafka import KafkaProducer

        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        # Produce test messages
        producer = KafkaProducer(
            bootstrap_servers=kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        test_events = [
            {"event_type": "order.created", "order_id": 1001, "amount": 99.99},
            {"event_type": "order.shipped", "order_id": 1001, "carrier": "FedEx"},
            {"event_type": "order.delivered", "order_id": 1001, "signature": True},
        ]

        for event in test_events:
            producer.send(kafka_topic, value=event)
        producer.flush()
        producer.close()

        # Configure connector
        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group="test-consumer",
            auto_offset_reset="earliest",
        )

        # Read events
        async with KafkaConnector(kafka_topic, config) as conn:
            batch = await conn.read_batch(max_messages=10, timeout_ms=10_000)

        assert len(batch) == 3, f"Expected 3 events, got {len(batch)}"

        # Verify events are parsed correctly
        event_types = [e.get("event_type") for e in batch]
        assert "order.created" in event_types
        assert "order.shipped" in event_types
        assert "order.delivered" in event_types

    @pytest.mark.asyncio
    async def test_read_batch_handles_empty_topic(
        self, kafka_container, kafka_bootstrap_servers
    ):
        """read_batch returns empty list for empty topic."""
        from kafka.admin import KafkaAdminClient, NewTopic

        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        # Create empty topic
        topic_name = f"empty-topic-{int(time.time())}"
        admin = KafkaAdminClient(bootstrap_servers=kafka_bootstrap_servers)
        admin.create_topics([NewTopic(name=topic_name, num_partitions=1, replication_factor=1)])
        admin.close()

        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group="test-empty-consumer",
            auto_offset_reset="earliest",
        )

        async with KafkaConnector(topic_name, config) as conn:
            batch = await conn.read_batch(max_messages=10, timeout_ms=2_000)

        assert batch == [], "Empty topic should return empty batch"


@requires_docker
class TestKafkaOffsetCommit:
    """Verify offset commit behavior."""

    @pytest.mark.asyncio
    async def test_ack_commits_offsets(
        self, kafka_container, kafka_bootstrap_servers, kafka_topic
    ):
        """ack() commits offsets so subsequent consumers start from committed position."""
        from kafka import KafkaProducer

        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        group_id = f"test-commit-group-{int(time.time())}"

        # Produce test messages
        producer = KafkaProducer(
            bootstrap_servers=kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        for i in range(5):
            producer.send(kafka_topic, value={"seq": i})
        producer.flush()
        producer.close()

        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group=group_id,
            auto_offset_reset="earliest",
        )

        # First consumer: read and ack
        async with KafkaConnector(kafka_topic, config) as conn:
            batch1 = await conn.read_batch(max_messages=3, timeout_ms=10_000)
            assert len(batch1) == 3
            await conn.ack()

        # Second consumer: should start from offset 3
        async with KafkaConnector(kafka_topic, config) as conn:
            batch2 = await conn.read_batch(max_messages=10, timeout_ms=5_000)
            # Should get remaining 2 messages
            assert len(batch2) == 2, f"Expected 2 remaining, got {len(batch2)}"


@requires_docker
class TestKafkaPartitionAssignment:
    """Verify partition handling."""

    @pytest.mark.asyncio
    async def test_reads_from_all_partitions(
        self, kafka_container, kafka_bootstrap_servers
    ):
        """Connector reads from all partitions of a multi-partition topic."""
        from kafka import KafkaProducer
        from kafka.admin import KafkaAdminClient, NewTopic

        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        # Create topic with 3 partitions
        topic_name = f"multi-partition-{int(time.time())}"
        admin = KafkaAdminClient(bootstrap_servers=kafka_bootstrap_servers)
        admin.create_topics([
            NewTopic(name=topic_name, num_partitions=3, replication_factor=1)
        ])
        admin.close()

        # Produce to specific partitions
        producer = KafkaProducer(
            bootstrap_servers=kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        for partition in range(3):
            for i in range(2):
                producer.send(
                    topic_name,
                    partition=partition,
                    value={"partition": partition, "seq": i},
                )
        producer.flush()
        producer.close()

        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group=f"test-multipart-{int(time.time())}",
            auto_offset_reset="earliest",
        )

        async with KafkaConnector(topic_name, config) as conn:
            batch = await conn.read_batch(max_messages=10, timeout_ms=15_000)

        # Should have 6 messages total (2 per partition)
        assert len(batch) == 6, f"Expected 6 from 3 partitions, got {len(batch)}"

        # Verify messages from all partitions
        partitions_seen = {e.get("partition") for e in batch}
        assert partitions_seen == {0, 1, 2}, "Should read from all partitions"


@requires_docker
class TestKafkaErrorHandling:
    """Verify error handling with real broker."""

    @pytest.mark.asyncio
    async def test_handles_invalid_topic(self, kafka_container, kafka_bootstrap_servers):
        """Gracefully handles reading from non-existent topic."""
        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group="test-invalid",
            auto_offset_reset="earliest",
        )

        # Non-existent topic should return empty (Kafka auto-creates topics by default)
        async with KafkaConnector("nonexistent-topic-xyz", config) as conn:
            batch = await conn.read_batch(max_messages=10, timeout_ms=2_000)

        # Should return empty, not crash
        assert batch == []

    @pytest.mark.asyncio
    async def test_handles_malformed_json(
        self, kafka_container, kafka_bootstrap_servers
    ):
        """Malformed JSON messages are skipped, not crash."""
        from kafka import KafkaProducer
        from kafka.admin import KafkaAdminClient, NewTopic

        from streamforge.config import KafkaConfig
        from streamforge.connectors.kafka import KafkaConnector

        topic_name = f"malformed-json-{int(time.time())}"
        admin = KafkaAdminClient(bootstrap_servers=kafka_bootstrap_servers)
        admin.create_topics([
            NewTopic(name=topic_name, num_partitions=1, replication_factor=1)
        ])
        admin.close()

        # Produce mix of valid and invalid JSON
        producer = KafkaProducer(bootstrap_servers=kafka_bootstrap_servers)
        producer.send(topic_name, value=b'{"valid": true}')
        producer.send(topic_name, value=b'not json at all')
        producer.send(topic_name, value=b'{"also_valid": true}')
        producer.flush()
        producer.close()

        config = KafkaConfig(
            bootstrap_servers=[kafka_bootstrap_servers],
            consumer_group=f"test-malformed-{int(time.time())}",
            auto_offset_reset="earliest",
        )

        async with KafkaConnector(topic_name, config) as conn:
            batch = await conn.read_batch(max_messages=10, timeout_ms=10_000)

        # Should get 2 valid messages, skip the invalid one
        assert len(batch) == 2, f"Expected 2 valid messages, got {len(batch)}"
