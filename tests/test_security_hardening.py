"""Security hardening tests — pre-demo CRITICALs.

TDD RED phase: all tests written before implementation.

Covers:
1. PII scrubbing in LLM prompts (CRITICAL-001)
2. Kafka SASL_SSL default in production (CRITICAL-012)
3. File permissions on written artifacts (CRITICAL-004, HIGH-005)
4. Max event size guard in flatten_nested (HIGH-024)
5. Line length guard before ReDoS regex (HIGH-025)
"""

import os
import re
import stat
from pathlib import Path
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PII SCRUBBING IN LLM PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPiiScrubInPrompt:
    """Raw PII must never reach external LLM APIs."""

    def test_scrub_event_for_prompt_masks_emails(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"user_email": "alice@stripe.com", "status": "completed"}
        scrubbed = _scrub_event_for_prompt(event)
        assert "alice@stripe.com" not in str(scrubbed)
        assert "status" in scrubbed
        assert scrubbed["status"] == "completed"

    def test_scrub_event_for_prompt_masks_card_numbers(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"card_last_four": "4242", "amount": 99.99}
        scrubbed = _scrub_event_for_prompt(event)
        assert "4242" not in str(scrubbed)
        assert scrubbed["amount"] == 99.99

    def test_scrub_event_for_prompt_preserves_non_pii(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"event_id": "abc-123", "currency": "USD", "status": "pending"}
        scrubbed = _scrub_event_for_prompt(event)
        assert scrubbed["event_id"] == "abc-123"
        assert scrubbed["currency"] == "USD"

    def test_scrub_handles_nested_pii(self):
        from streamforge.inference import _scrub_event_for_prompt
        event = {"user": {"email": "bob@test.com", "name": "Bob"}, "amount": 50}
        scrubbed = _scrub_event_for_prompt(event)
        assert "bob@test.com" not in str(scrubbed)
        assert scrubbed["amount"] == 50

    def test_build_inference_prompt_uses_scrubbed_events(self):
        """The actual prompt builder must use scrubbed events."""
        from streamforge.inference import build_inference_prompt
        field_stats = {"email": ["alice@stripe.com"], "status": ["ok"]}
        presence = {"email": 1.0, "status": 1.0}
        events = [{"email": "alice@stripe.com", "status": "ok"}]
        prompt = build_inference_prompt(field_stats, presence, events)
        assert "alice@stripe.com" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 2. KAFKA SASL_SSL DEFAULT IN PRODUCTION
# ═══════════════════════════════════════════════════════════════════════════════

class TestKafkaSecureDefault:
    """Kafka must reject PLAINTEXT in production mode."""

    def test_validate_rejects_plaintext_in_prod(self):
        from streamforge.config import ConfigValidationError, validate_config
        with pytest.raises(ConfigValidationError, match="[Pp]laintext|PLAINTEXT"):
            validate_config(
                kafka_brokers="broker:9092",
                stream_uri="kafka://events.payments",
                kafka_security_protocol="PLAINTEXT",
                env="prod",
            )

    def test_validate_allows_plaintext_in_dev(self):
        from streamforge.config import validate_config
        # Should NOT raise
        validate_config(
            kafka_brokers="broker:9092",
            stream_uri="kafka://events.payments",
            kafka_security_protocol="PLAINTEXT",
            env="dev",
        )

    def test_validate_allows_sasl_ssl_in_prod(self):
        from streamforge.config import validate_config
        validate_config(
            kafka_brokers="broker:9092",
            stream_uri="kafka://events.payments",
            kafka_security_protocol="SASL_SSL",
            env="prod",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FILE PERMISSIONS ON WRITTEN ARTIFACTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilePermissions:
    """All written files must have restrictive permissions."""

    def test_secure_write_sets_600_permissions(self, tmp_path):
        from streamforge.schema_writer import _secure_write
        target = tmp_path / "test.yaml"
        _secure_write(target, "secret content")
        assert target.exists()
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_secure_write_content_is_correct(self, tmp_path):
        from streamforge.schema_writer import _secure_write
        target = tmp_path / "test.yaml"
        _secure_write(target, "hello world")
        assert target.read_text() == "hello world"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MAX EVENT SIZE GUARD
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventSizeGuard:
    """flatten_nested must handle oversized and deeply nested events safely."""

    def test_flatten_respects_max_depth(self):
        from streamforge.sampler import flatten_nested
        # Build a 20-level deep nested object
        obj = {"value": "leaf"}
        for i in range(20):
            obj = {f"level_{i}": obj}
        flat = flatten_nested(obj)
        # Should not recurse all 20 levels — capped at MAX_DEPTH
        if flat:
            max_dots = max(k.count(".") for k in flat.keys())
            assert max_dots <= 10, f"Recursion depth {max_dots} exceeds max 10"
        # Empty result is also acceptable (capped before first key)

    def test_flatten_respects_max_keys(self):
        from streamforge.sampler import flatten_nested
        # Build an object with 2000 keys
        obj = {f"field_{i}": f"value_{i}" for i in range(2000)}
        flat = flatten_nested(obj)
        assert len(flat) <= 1000, f"Got {len(flat)} keys, expected max 1000"

    def test_flatten_normal_event_unchanged(self):
        from streamforge.sampler import flatten_nested
        event = {"id": "abc", "user": {"email": "a@b.com"}, "amount": 99}
        flat = flatten_nested(event)
        assert flat["id"] == "abc"
        assert flat["user.email"] == "a@b.com"
        assert flat["amount"] == 99


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LINE LENGTH GUARD BEFORE REDOS REGEX
# ═══════════════════════════════════════════════════════════════════════════════

class TestLineLengthGuard:
    """Oversized lines must be rejected before regex parsing."""

    def test_parse_resilient_rejects_oversized_line(self):
        from streamforge.sampler import parse_resilient
        # 100KB line of garbage — should not hang or crash
        huge_line = "{" * 100_000
        result, confidence = parse_resilient(huge_line)
        # Should return empty/low confidence, not hang
        assert confidence < 1.0

    def test_parse_resilient_normal_json_works(self):
        from streamforge.sampler import parse_resilient
        line = '{"id": "abc", "value": 42}'
        result, confidence = parse_resilient(line)
        assert confidence == 1.0
        assert result["id"] == "abc"

    def test_streaming_sample_skips_oversized_lines(self, tmp_path):
        from streamforge.sampler import streaming_resilient_sample_from_folder
        # Write a file with one normal and one oversized line
        f = tmp_path / "events.ndjson"
        normal = '{"id": "abc", "value": 42}'
        oversized = '{"big": "' + "x" * 100_000 + '"}'
        f.write_text(normal + "\n" + oversized + "\n")
        clean, partial, total, stats = streaming_resilient_sample_from_folder(str(tmp_path), 100)
        # Normal line should be parsed, oversized should be skipped
        assert len(clean) >= 1
        assert stats["skipped"] >= 1
