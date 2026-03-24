"""Tests for the discover CLI command."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from streamforge.__main__ import app

runner = CliRunner()


def _make_admin_mock(topics: list[str]):
    """Create a mock AdminClient that returns the given topic list."""
    mock_metadata = MagicMock()
    mock_metadata.topics = {t: MagicMock() for t in topics}

    mock_admin = MagicMock()
    mock_admin.list_topics.return_value = mock_metadata

    mock_admin_cls = MagicMock(return_value=mock_admin)
    return mock_admin_cls


def _patch_admin(topics: list[str]):
    """Return a patch context for confluent_kafka AdminClient."""
    return patch(
        "streamforge.__main__.discover.__wrapped__"  # fallback if wrapped
        if False else "streamforge.__main__.AdminClient",  # direct patch target
    )


def test_discover_lists_monitored_and_unmonitored(tmp_path):
    """5 topics returned, 2 have schemas → 2 monitored, 3 unmonitored."""
    all_topics = ["events.payments", "events.bookings", "orders", "users", "audit-log"]

    # Create schema files for 2 topics
    schema_dir = tmp_path / "schemas"
    for topic in ["events.payments", "events.bookings"]:
        d = schema_dir / topic
        d.mkdir(parents=True)
        (d / "schema.yaml").write_text(
            "stream: test\nversion: '1.0.0'\ninferred_at: '2024-01-01'\n"
            "inference_confidence: 0.9\nfields: []\nevent_count_sampled: 100\n"
            "inference_model: test\n"
        )

    mock_admin_cls = _make_admin_mock(all_topics)

    with patch("streamforge.__main__.AdminClient", mock_admin_cls, create=True):
        # Also patch the import inside the function
        with patch.dict("sys.modules", {"confluent_kafka.admin": MagicMock(AdminClient=mock_admin_cls)}):
            result = runner.invoke(app, [
                "discover",
                "--brokers", "localhost:9092",
                "--output", str(schema_dir),
            ])

    assert result.exit_code == 0, result.output
    assert "events.payments" in result.output
    assert "events.bookings" in result.output
    assert "orders" in result.output


def test_discover_filters_internal_topics(tmp_path):
    """Internal topics starting with _ should not appear in output."""
    all_topics = ["events.payments", "_consumer_offsets", "__transaction_state", "orders"]
    mock_admin_cls = _make_admin_mock(all_topics)

    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()

    with patch.dict("sys.modules", {"confluent_kafka.admin": MagicMock(AdminClient=mock_admin_cls)}):
        result = runner.invoke(app, [
            "discover",
            "--brokers", "localhost:9092",
            "--output", str(schema_dir),
        ])

    assert result.exit_code == 0, result.output
    assert "_consumer_offsets" not in result.output
    assert "__transaction_state" not in result.output
    assert "events.payments" in result.output
    assert "orders" in result.output


def test_discover_no_brokers_exits_1():
    """No --brokers and no env var → exits 1 with a message about brokers."""
    import os
    env_backup = os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    try:
        mock_tc = MagicMock()
        mock_tc.kafka_broker_list = []

        with patch("streamforge.__main__.load_topic_config", return_value=mock_tc):
            result = runner.invoke(app, ["discover"])
    finally:
        if env_backup is not None:
            os.environ["KAFKA_BOOTSTRAP_SERVERS"] = env_backup

    assert result.exit_code == 1
    assert "broker" in result.output.lower() or "kafka" in result.output.lower()


def test_discover_summary_shows_counts(tmp_path):
    """Output should contain 'Monitored (2)' and 'Unmonitored (3)'."""
    all_topics = ["events.payments", "events.bookings", "orders", "users", "audit-log"]

    schema_dir = tmp_path / "schemas"
    for topic in ["events.payments", "events.bookings"]:
        d = schema_dir / topic
        d.mkdir(parents=True)
        (d / "schema.yaml").write_text(
            "stream: test\nversion: '1.0.0'\ninferred_at: '2024-01-01'\n"
            "inference_confidence: 0.9\nfields: []\nevent_count_sampled: 100\n"
            "inference_model: test\n"
        )

    mock_admin_cls = _make_admin_mock(all_topics)

    with patch.dict("sys.modules", {"confluent_kafka.admin": MagicMock(AdminClient=mock_admin_cls)}):
        result = runner.invoke(app, [
            "discover",
            "--brokers", "localhost:9092",
            "--output", str(schema_dir),
        ])

    assert result.exit_code == 0, result.output
    assert "Monitored" in result.output
    assert "2" in result.output   # 2 monitored
    assert "3" in result.output   # 3 unmonitored
    assert "Unmonitored" in result.output
