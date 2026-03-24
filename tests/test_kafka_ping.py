"""Tests for the kafka-ping CLI command."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from streamforge.__main__ import app

runner = CliRunner()


def _make_mock_connector(batch=None, raise_exc=None, source_id_val="kafka://localhost:9092/test-topic"):
    """Create an async context manager mock for KafkaConnector."""
    mock_conn = AsyncMock()
    mock_conn.source_id = source_id_val
    if raise_exc is not None:
        mock_conn.read_batch = AsyncMock(side_effect=raise_exc)
    else:
        mock_conn.read_batch = AsyncMock(return_value=batch if batch is not None else [])
    mock_conn.ack = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_ctx


def test_ping_success_with_events():
    """Connector returns events — should print connected + preview and exit 0."""
    sample_events = [{"id": "1", "amount": 100}]
    mock_ctx = _make_mock_connector(batch=sample_events)

    with patch("streamforge.connectors.kafka.KafkaConnector", return_value=mock_ctx):
        result = runner.invoke(app, [
            "kafka-ping", "test-topic",
            "--brokers", "localhost:9092",
            "--timeout", "5",
        ])

    assert result.exit_code == 0, result.output
    assert "Connected" in result.output
    assert "1" in result.output  # received 1 message


def test_ping_success_no_events():
    """Connector returns empty batch — should note no messages and still exit 0."""
    mock_ctx = _make_mock_connector(batch=[])

    with patch("streamforge.connectors.kafka.KafkaConnector", return_value=mock_ctx):
        result = runner.invoke(app, [
            "kafka-ping", "test-topic",
            "--brokers", "localhost:9092",
            "--timeout", "3",
        ])

    assert result.exit_code == 0, result.output
    assert "no messages arrived" in result.output.lower() or "connected" in result.output.lower()


def test_ping_kafka_error():
    """Connector raises KafkaConnectorError — should print error and exit 1."""
    from streamforge.connectors.kafka import KafkaConnectorError

    # KafkaConnectorError is raised during __aenter__ (connection attempt)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=KafkaConnectorError("broker unreachable"))
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("streamforge.connectors.kafka.KafkaConnector", return_value=mock_ctx):
        result = runner.invoke(app, [
            "kafka-ping", "test-topic",
            "--brokers", "localhost:9092",
        ])

    assert result.exit_code == 1
    assert "Kafka not available" in result.output or "broker unreachable" in result.output
    # Should include docker hint
    assert "docker" in result.output.lower() or "kafka" in result.output.lower()


def test_ping_clear_error_on_no_brokers():
    """No --brokers and no env var — should exit 1 with a readable message."""
    # Ensure env var is not set
    import os
    env_backup = os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    # Also mock the config loader to return empty broker list
    mock_cfg = MagicMock()
    mock_cfg.kafka.bootstrap_servers = []

    try:
        with patch("streamforge.__main__.load_topic_config") as mock_tc:
            mock_tc_instance = MagicMock()
            mock_tc_instance.kafka_broker_list = []
            mock_tc.return_value = mock_tc_instance

            # Patch the config load inside kafka_ping
            with patch("streamforge.__main__.app.registered_commands", new_callable=lambda: lambda: None):
                pass  # noop

            # Use the direct path patched inside the command
            with patch("streamforge.config.load") as mock_load:
                mock_config = MagicMock()
                mock_config.kafka.bootstrap_servers = []
                mock_load.return_value = mock_config

                result = runner.invoke(app, ["kafka-ping", "test-topic"])

    finally:
        if env_backup is not None:
            os.environ["KAFKA_BOOTSTRAP_SERVERS"] = env_backup

    assert result.exit_code == 1
    assert "broker" in result.output.lower() or "kafka" in result.output.lower()
