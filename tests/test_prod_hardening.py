"""Tests for production hardening — Phase 1.

Tests written FIRST (TDD RED phase). Implementation follows.

Covers:
1. Audit trail ON by default
2. API key sanitization in exception logs
3. print() replaced with logger in watch loops
4. PII redaction in registry samples (toggleable per topic)
5. Startup config validation
"""

import json
import logging
import os
import re
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AUDIT TRAIL ON BY DEFAULT
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditDefaultOn:
    """Audit logging must be ON by default — SOC2 requirement."""

    def test_audit_enabled_when_env_not_set(self):
        """When STREAMFORGE_AUDIT is not set, audit should be enabled."""
        env = {k: v for k, v in os.environ.items() if k != "STREAMFORGE_AUDIT"}
        with patch.dict(os.environ, env, clear=True):
            # Force re-evaluation
            import importlib
            from streamforge import audit
            audit._configured = False
            audit._ensure_configured()
            assert audit._audit_logger.isEnabledFor(logging.DEBUG)

    def test_audit_disabled_when_explicitly_off(self):
        """When STREAMFORGE_AUDIT=0, audit should be disabled."""
        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "0"}):
            from streamforge import audit
            audit._configured = False
            audit._ensure_configured()
            assert not audit._audit_logger.isEnabledFor(logging.DEBUG)

    def test_audit_enabled_when_explicitly_on(self):
        """When STREAMFORGE_AUDIT=1, audit should be enabled."""
        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1"}):
            from streamforge import audit
            audit._configured = False
            audit._ensure_configured()
            assert audit._audit_logger.isEnabledFor(logging.DEBUG)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. API KEY SANITIZATION IN EXCEPTION LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class TestApiKeySanitization:
    """API keys must never appear in log output."""

    def test_sanitize_api_key_in_string(self):
        """sanitize_for_logging must mask API key patterns."""
        from streamforge.inference import _sanitize_for_logging

        msg = "AuthenticationError: Incorrect API key provided: sk-proj-abc123xyz"
        sanitized = _sanitize_for_logging(msg)
        assert "sk-proj-abc123xyz" not in sanitized
        assert "sk-proj-" not in sanitized or "***" in sanitized

    def test_sanitize_groq_key(self):
        """Must mask gsk_ prefixed keys."""
        from streamforge.inference import _sanitize_for_logging

        msg = "Error with key gsk_SM7YW2qxQ2FjRisGo8OiWGdyb3FY"
        sanitized = _sanitize_for_logging(msg)
        assert "gsk_SM7YW2" not in sanitized

    def test_sanitize_preserves_non_key_content(self):
        """Must not destroy non-key parts of the message."""
        from streamforge.inference import _sanitize_for_logging

        msg = "Connection timeout after 30 seconds to api.groq.com"
        sanitized = _sanitize_for_logging(msg)
        assert "Connection timeout" in sanitized
        assert "30 seconds" in sanitized

    def test_sanitize_openrouter_key(self):
        """Must mask sk-or- prefixed keys."""
        from streamforge.inference import _sanitize_for_logging

        msg = "Invalid key: sk-or-v1-aabd0ec8a964ecc59b8cf779"
        sanitized = _sanitize_for_logging(msg)
        assert "sk-or-v1-aabd0ec8" not in sanitized


# ═══════════════════════════════════════════════════════════════════════════════
# 3. NO print() IN WATCH LOOPS
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoPrintInWatch:
    """Watch loop code must use logger, not print()."""

    def test_no_bare_print_in_watch_module(self):
        """watch.py should not contain bare print() calls for operational output."""
        import ast
        from pathlib import Path

        watch_path = Path(__file__).parent.parent / "streamforge" / "detector" / "watch.py"
        source = watch_path.read_text()
        tree = ast.parse(source)

        print_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Check for bare print() calls
                if isinstance(func, ast.Name) and func.id == "print":
                    print_calls.append(node.lineno)

        assert print_calls == [], (
            f"watch.py has print() calls at lines {print_calls}. "
            f"Use logger.info() instead for structured logging."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PII REDACTION IN REGISTRY SAMPLES (toggleable per topic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPiiRedactionInRegistry:
    """Sample values for PII-flagged fields must be redacted before persisting."""

    def test_pii_field_samples_redacted_on_record(self):
        """When recording a field with pii_categories, sample values must be redacted."""
        from streamforge.field_registry import FieldTypeRegistry

        registry = FieldTypeRegistry()
        registry.record(
            field_path="user_email",
            field_type="email",
            confidence=0.95,
            stream_name="events.payments",
            sample_values=["alice@stripe.com", "bob@example.com", "carol@test.io"],
            pii_categories=["email"],
        )

        obs = registry._observations["user_email"]
        # Samples must not contain actual email addresses
        for sample in obs.sample_values:
            assert "@" not in str(sample), f"PII value not redacted: {sample}"

    def test_non_pii_field_samples_preserved(self):
        """Fields without PII categories should keep their sample values."""
        from streamforge.field_registry import FieldTypeRegistry

        registry = FieldTypeRegistry()
        registry.record(
            field_path="status",
            field_type="string",
            confidence=0.90,
            stream_name="events.payments",
            sample_values=["completed", "pending", "failed"],
            pii_categories=[],
        )

        obs = registry._observations["status"]
        assert "completed" in obs.sample_values

    def test_pii_redaction_toggleable_via_env(self):
        """STREAMFORGE_REDACT_PII=0 should disable redaction (for dev/debug)."""
        from streamforge.field_registry import FieldTypeRegistry

        with patch.dict(os.environ, {"STREAMFORGE_REDACT_PII": "0"}):
            registry = FieldTypeRegistry()
            registry.record(
                field_path="user_email",
                field_type="email",
                confidence=0.95,
                stream_name="events.payments",
                sample_values=["alice@stripe.com"],
                pii_categories=["email"],
            )
            obs = registry._observations["user_email"]
            # When redaction is off, values should be preserved
            assert "alice@stripe.com" in obs.sample_values

    def test_redaction_placeholder_includes_pii_category(self):
        """Redacted values should indicate what category was redacted."""
        from streamforge.field_registry import FieldTypeRegistry

        registry = FieldTypeRegistry()
        registry.record(
            field_path="card_number",
            field_type="string",
            confidence=0.95,
            stream_name="events.payments",
            sample_values=["4242424242424242"],
            pii_categories=["card_number"],
        )

        obs = registry._observations["card_number"]
        assert any("card_number" in str(s) for s in obs.sample_values), (
            f"Redacted placeholder should include PII category, got: {obs.sample_values}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. STARTUP CONFIG VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartupConfigValidation:
    """StreamForge must validate config and fail fast before entering watch loop."""

    def test_validate_config_function_exists(self):
        """A validate_config function must exist."""
        from streamforge.config import validate_config
        assert callable(validate_config)

    def test_validate_missing_kafka_brokers_raises(self):
        """Must raise if KAFKA_BOOTSTRAP_SERVERS is empty/missing for kafka:// URIs."""
        from streamforge.config import validate_config, ConfigValidationError

        with pytest.raises(ConfigValidationError, match="[Kk]afka.*broker"):
            validate_config(kafka_brokers="", stream_uri="kafka://events.payments")

    def test_validate_valid_config_passes(self):
        """Valid config should not raise."""
        from streamforge.config import validate_config

        # Should not raise
        validate_config(
            kafka_brokers="localhost:9092",
            stream_uri="kafka://events.payments",
        )

    def test_validate_file_stream_no_kafka_required(self):
        """File-based streams should not require Kafka brokers."""
        from streamforge.config import validate_config

        # Should not raise
        validate_config(
            kafka_brokers="",
            stream_uri="events/payments/stream_v1",
        )

    def test_validate_schemas_dir_writable(self):
        """Must verify the schemas output directory is writable."""
        from streamforge.config import validate_config, ConfigValidationError

        with pytest.raises(ConfigValidationError, match="[Ss]chemas.*writ"):
            validate_config(
                kafka_brokers="localhost:9092",
                stream_uri="kafka://events.payments",
                schemas_dir="/nonexistent/readonly/path",
            )
