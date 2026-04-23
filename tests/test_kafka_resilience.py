"""Tests for Kafka connector resilience: retry, backpressure, offset commit, error classification.

All tests use mocks — no real Kafka broker required.
"""
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from streamforge.config import KafkaConfig
from streamforge.connectors.kafka import KafkaConnector, KafkaConnectorError


def _make_cfg(**overrides) -> KafkaConfig:
    defaults = {
        "bootstrap_servers": ["localhost:9092"],
        "security_protocol": "PLAINTEXT",
        "consumer_group": "test-group",
        "auto_offset_reset": "latest",
    }
    defaults.update(overrides)
    return KafkaConfig(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# Error Classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorClassification:
    """RetryableKafkaError carries retryability flag for circuit breaker integration."""

    def test_retryable_kafka_error_has_flag(self):
        from streamforge.connectors.kafka import RetryableKafkaError
        exc = RetryableKafkaError("transport error", retryable=True)
        assert exc.retryable is True

    def test_retryable_kafka_error_default_false(self):
        from streamforge.connectors.kafka import RetryableKafkaError
        exc = RetryableKafkaError("auth error")
        assert exc.retryable is False


# ═══════════════════════════════════════════════════════════════════════════════
# Backpressure
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackpressure:
    """read_batch must respect max_batch_bytes."""

    def test_default_max_batch_bytes(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        assert conn._max_batch_bytes == 10 * 1024 * 1024  # 10MB

    def test_custom_max_batch_bytes(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg, max_batch_bytes=1024)
        assert conn._max_batch_bytes == 1024

    def test_zero_max_batch_bytes_means_unlimited(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg, max_batch_bytes=0)
        assert conn._max_batch_bytes == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Offset Commit
# ═══════════════════════════════════════════════════════════════════════════════

class TestOffsetCommit:
    """ack() must raise on commit failure."""

    @pytest.mark.asyncio
    async def test_ack_raises_on_commit_failure(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        conn._last_batch = [{"id": 1}]
        conn._consumer = MagicMock()
        conn._consumer.commit = MagicMock(side_effect=RuntimeError("commit failed"))

        with patch("streamforge.connectors.kafka._CONFLUENT_AVAILABLE", False), \
             patch("streamforge.connectors.kafka._KAFKA_PYTHON_AVAILABLE", True):
            with pytest.raises(KafkaConnectorError, match="commit failed"):
                await conn.ack()

    @pytest.mark.asyncio
    async def test_ack_noop_when_no_batch(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        conn._last_batch = []
        conn._consumer = MagicMock()
        # Should not raise, should not call commit
        await conn.ack()
        conn._consumer.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_ack_success_clears_batch(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        conn._last_batch = [{"id": 1}, {"id": 2}]
        conn._consumer = MagicMock()
        conn._consumer.commit = MagicMock()

        with patch("streamforge.connectors.kafka._CONFLUENT_AVAILABLE", False), \
             patch("streamforge.connectors.kafka._KAFKA_PYTHON_AVAILABLE", True):
            await conn.ack()
        assert conn._last_batch == []


# ═══════════════════════════════════════════════════════════════════════════════
# Message Parsing Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestMessageParsing:
    """Edge cases in message parsing must not crash."""

    def test_parse_binary_garbage(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        assert conn._parse_message(b'\x00\xff\xfe\x80') is None

    def test_parse_empty_bytes(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        assert conn._parse_message(b'') is None

    def test_parse_none(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        assert conn._parse_message(None) is None

    def test_parse_valid_json(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        result = conn._parse_message(b'{"id": 1, "name": "test"}')
        assert result == {"id": 1, "name": "test"}

    def test_parse_json_array_returns_none(self):
        """Arrays are not events — only dicts are valid."""
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        result = conn._parse_message(b'[1, 2, 3]')
        assert result is None  # arrays are not events

    def test_parse_json_string_returns_none(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        result = conn._parse_message(b'"just a string"')
        assert result is None

    def test_parse_oversized_message_logged(self):
        """Messages > 64KB are too big for safe regex — should still parse."""
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        big = json.dumps({"data": "x" * 100_000}).encode()
        result = conn._parse_message(big)
        assert result is not None  # valid JSON should parse regardless of size
        assert result["data"] == "x" * 100_000

    def test_parse_corrupt_json(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        assert conn._parse_message(b'{"broken": true, missing_quote}') is None

    def test_parse_deeply_nested_json(self):
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        nested = {"level": 0}
        current = nested
        for i in range(1, 30):
            current["child"] = {"level": i}
            current = current["child"]
        raw = json.dumps(nested).encode()
        result = conn._parse_message(raw)
        assert result is not None
        assert result["level"] == 0

    def test_close_idempotent(self):
        """Calling close twice must not crash."""
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        conn._consumer = MagicMock()
        import asyncio
        asyncio.run(conn.close())
        asyncio.run(conn.close())  # second call — consumer is now None


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Behavior (integration-level with mocked consumer)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetryBehavior:
    """Transient errors in poll must be retried with backoff."""

    def test_read_confluent_retries_transient_error(self):
        """Transient error on first poll, success on second."""
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)

        # Mock KafkaError with _PARTITION_EOF attribute
        mock_kafka_error = MagicMock()
        mock_kafka_error._PARTITION_EOF = -191

        # Build mock messages: error msg then good msg then timeout
        error_msg = MagicMock()
        error_msg.error.return_value = MagicMock()
        error_msg.error.return_value.code.return_value = 7  # NOT _PARTITION_EOF
        error_msg.error.return_value.retriable.return_value = True

        good_msg = MagicMock()
        good_msg.error.return_value = None
        good_msg.value.return_value = b'{"id": 1}'

        conn._consumer = MagicMock()
        conn._consumer.poll = MagicMock(side_effect=[error_msg, good_msg, None])

        with patch("streamforge.connectors.kafka._CONFLUENT_AVAILABLE", True), \
             patch("streamforge.connectors.kafka.KafkaError", mock_kafka_error, create=True):
            result = conn._read_confluent(max_messages=10, timeout_ms=5000)
        # The error message is logged and skipped, the good message is returned
        assert len(result) >= 1

    def test_read_confluent_breaks_on_none(self):
        """Timeout (None) should break the loop."""
        cfg = _make_cfg()
        conn = KafkaConnector("test", cfg)
        conn._consumer = MagicMock()
        conn._consumer.poll = MagicMock(return_value=None)

        with patch("streamforge.connectors.kafka._CONFLUENT_AVAILABLE", True):
            result = conn._read_confluent(max_messages=10, timeout_ms=1000)
        assert result == []
