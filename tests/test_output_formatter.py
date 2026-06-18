"""Tests for human-readable output formatting."""
from streamforge.output_formatter import (
    _humanize_type,
    describe_drift,
    format_discover_panel,
    format_init_success,
    format_watch_tick,
)


def test_describe_drift_field_removed():
    result = describe_drift("field_removed", "amount")
    assert result == "'amount' field was removed"
    # No technical jargon
    assert "field_removed" not in result


def test_describe_drift_type_changed_humanizes_types():
    result = describe_drift("type_changed", "created_at", "timestamp_epoch_ms", "timestamp_iso8601")
    assert "epoch timestamp" in result
    assert "ISO date string" in result
    assert "timestamp_epoch_ms" not in result
    assert "timestamp_iso8601" not in result


def test_describe_drift_field_added():
    result = describe_drift("field_added", "refund_reason")
    assert "refund_reason" in result
    assert "field_added" not in result


def test_describe_drift_presence_drift_with_rates():
    result = describe_drift("presence_drift", "amount", 0.98, 0.02)
    assert "amount" in result
    assert "98%" in result
    assert "2%" in result


def test_humanize_type_known():
    assert _humanize_type("timestamp_epoch_ms") == "epoch timestamp"
    assert _humanize_type("string") == "text"
    assert _humanize_type("float") == "decimal number"
    assert _humanize_type("boolean") == "true/false"


def test_humanize_type_unknown_falls_back():
    result = _humanize_type("some_custom_type")
    assert result == "some custom type"  # underscores → spaces


def test_format_watch_tick_clean():
    result = format_watch_tick("events.payments", 200, is_clean=True)
    assert "events.payments" in result
    assert "200 events checked" in result
    assert "no breaking changes" in result
    assert "✓" in result


def test_format_watch_tick_drift():
    result = format_watch_tick("events.payments", 200, is_clean=False)
    assert "🔴" in result
    assert "BREAKING CHANGE" in result


def test_format_discover_panel_shows_exposed_count():
    result = format_discover_panel(
        "localhost:9092",
        monitored=["events.payments"],
        unmonitored=["orders", "users", "audit-log"]
    )
    assert "3" in result  # 3 exposed
    assert "NO schema contract" in result
    assert "orders" in result


def test_format_discover_panel_no_technical_jargon():
    result = format_discover_panel("localhost:9092", [], ["orders", "users"])
    assert "schema.yaml" not in result
    assert "InferredSchema" not in result
    assert "DriftReport" not in result


def test_format_init_success():
    result = format_init_success("events.payments", 12, 0.91)
    assert "events.payments" in result
    assert "12 fields" in result
    assert "91%" in result
    assert "streamforge watch" in result
