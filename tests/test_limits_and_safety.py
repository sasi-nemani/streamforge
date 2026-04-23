"""Tests for field limits, pathological input, and thread-safety fixes."""
import json
import logging
import os
import threading
from pathlib import Path

import pytest


class TestFieldRegistryThreadSafety:
    """FieldTypeRegistry.record() must be thread-safe."""

    def test_registry_has_lock(self):
        from streamforge.field_registry import FieldTypeRegistry
        reg = FieldTypeRegistry()
        assert hasattr(reg, "_lock"), "Registry must have _lock for thread safety"

    def test_concurrent_record_preserves_all_fields(self):
        from streamforge.field_registry import FieldTypeRegistry
        reg = FieldTypeRegistry()
        errors = []

        def record_fields(thread_id):
            try:
                for i in range(20):
                    reg.record(f"thread{thread_id}_field{i}", "string", 0.9, "test", [f"v{i}"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_fields, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent record errors: {errors}"
        # 10 threads x 20 fields = 200 unique fields
        assert len(reg._observations) == 200, f"Expected 200 fields, got {len(reg._observations)}"

    def test_concurrent_record_same_field_count_correct(self):
        from streamforge.field_registry import FieldTypeRegistry
        reg = FieldTypeRegistry()
        errors = []

        def record_same():
            try:
                for _ in range(50):
                    reg.record("shared", "string", 0.9, "test", ["v"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_same) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 10 threads x 50 records = 500 total. observation_count should be 500
        assert reg._observations["shared"].observation_count == 500, \
            f"Expected 500, got {reg._observations['shared'].observation_count}"


class TestFlattenLimits:
    """Sampler must handle high-cardinality and deeply nested events."""

    def test_1200_fields_not_silently_dropped(self):
        from streamforge.sampler import flatten_nested
        # Create event with 1200 top-level fields
        event = {f"field_{i}": f"value_{i}" for i in range(1200)}
        result = flatten_nested(event)
        # With new limit of 1000, should get 1000 (not 500)
        assert len(result) >= 1000, f"Expected >=1000 fields, got {len(result)}"

    def test_deep_nesting_logs_warning(self, caplog):
        from streamforge.sampler import flatten_nested
        # Build 15-level deep nesting
        event = {"level_0": "leaf"}
        current = event
        for i in range(1, 15):
            current["child"] = {f"level_{i}": "leaf"}
            current = current["child"]
        import streamforge.sampler as smod
        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        handler.setLevel(logging.WARNING)
        smod.logger.addHandler(handler)
        try:
            flatten_nested(event)
        finally:
            smod.logger.removeHandler(handler)
        # Should warn about depth exceeded
        warnings = [r.getMessage() for r in records]
        assert any("depth" in w.lower() for w in warnings), \
            f"Expected depth warning. Got: {warnings}"

    def test_null_bytes_in_field_names_sanitized(self):
        from streamforge.sampler import flatten_nested
        event = {"normal": "ok", "evil\x00field": "attack", "clean": "fine"}
        result = flatten_nested(event)
        for key in result:
            assert "\x00" not in key, f"Null byte found in field name: {key!r}"

    def test_max_flatten_keys_configurable(self, monkeypatch):
        monkeypatch.setenv("STREAMFORGE_MAX_FLATTEN_KEYS", "50")
        # Re-import to pick up env var
        import importlib
        import streamforge.sampler as smod
        importlib.reload(smod)
        event = {f"f{i}": i for i in range(100)}
        result = smod.flatten_nested(event)
        assert len(result) <= 50
        # Restore
        monkeypatch.delenv("STREAMFORGE_MAX_FLATTEN_KEYS", raising=False)
        importlib.reload(smod)


class TestKafkaPayloadGuard:
    """Oversized Kafka messages must be rejected, not parsed."""

    def test_oversized_message_rejected(self):
        from streamforge.connectors.kafka import KafkaConnector
        from streamforge.config import KafkaConfig
        conn = KafkaConnector("test", KafkaConfig(bootstrap_servers=["localhost:9092"]))
        # 6MB message (over 5MB default limit)
        big = json.dumps({"data": "x" * 6_000_000}).encode()
        result = conn._parse_message(big)
        assert result is None, "Oversized message must be rejected"

    def test_normal_message_still_parsed(self):
        from streamforge.connectors.kafka import KafkaConnector
        from streamforge.config import KafkaConfig
        conn = KafkaConnector("test", KafkaConfig(bootstrap_servers=["localhost:9092"]))
        normal = json.dumps({"id": 1, "name": "test"}).encode()
        result = conn._parse_message(normal)
        assert result == {"id": 1, "name": "test"}

    def test_exactly_at_limit_still_parsed(self):
        from streamforge.connectors.kafka import KafkaConnector
        from streamforge.config import KafkaConfig
        conn = KafkaConnector("test", KafkaConfig(bootstrap_servers=["localhost:9092"]))
        # Just under 5MB
        msg = json.dumps({"data": "x" * 4_999_000}).encode()
        result = conn._parse_message(msg)
        assert result is not None


class TestLargeStringFieldValues:
    """Fields with huge string values must be truncated during flattening."""

    def test_10mb_string_value_truncated(self):
        from streamforge.sampler import flatten_nested
        event = {"user_id": "12345", "description": "x" * 10_000_000}
        result = flatten_nested(event)
        assert "description" in result
        # Value should be truncated (not 10MB)
        assert len(str(result["description"])) <= 200_000, \
            f"String value too large: {len(str(result['description']))} chars"
