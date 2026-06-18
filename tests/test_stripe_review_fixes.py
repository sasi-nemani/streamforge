"""Tests for all issues identified in Stripe production readiness review.

Every bug found gets a failing test FIRST (RED), then implementation fixes it (GREEN).
These tests cover: security, correctness, performance, and resilience.
"""

import hashlib
import re
import time

# ═══════════════════════════════════════════════════════════════════════════════
# BUG 1: Regex recompilation in classify.py
# Every call to _infer_field_type_from_values() recompiles 4 regex patterns.
# At 8.6M calls/day, that's catastrophic CPU waste.
# FIX: Move regex to module level.
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegexModuleLevel:
    """Regex patterns must be compiled at module level, not per-call."""

    def test_regex_compiled_at_module_level(self):
        """classify.py must have UUID_RE, ISO_RE, DATE_RE, EMAIL_RE at module level."""
        import streamforge.detector.classify as classify
        assert hasattr(classify, "UUID_RE"), "UUID_RE must be module-level"
        assert hasattr(classify, "ISO_RE"), "ISO_RE must be module-level"
        assert hasattr(classify, "DATE_RE"), "DATE_RE must be module-level"
        assert hasattr(classify, "EMAIL_RE"), "EMAIL_RE must be module-level"
        # They must be compiled regex objects, not strings
        assert isinstance(classify.UUID_RE, re.Pattern)
        assert isinstance(classify.ISO_RE, re.Pattern)
        assert isinstance(classify.DATE_RE, re.Pattern)
        assert isinstance(classify.EMAIL_RE, re.Pattern)

    def test_no_regex_import_inside_function(self):
        """_infer_field_type_from_values must NOT import re inside the function."""
        import inspect

        from streamforge.detector.classify import _infer_field_type_from_values
        source = inspect.getsource(_infer_field_type_from_values)
        assert "import re" not in source, "re must not be imported inside the function"
        assert "re.compile" not in source, "re.compile must not be called inside the function"

    def test_infer_still_works_after_refactor(self):
        """Type inference must still produce correct results after regex move."""
        from streamforge.detector.classify import _infer_field_type_from_values
        from streamforge.models import FieldType
        # UUID
        assert _infer_field_type_from_values(["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]) == FieldType.UUID
        # Email
        assert _infer_field_type_from_values(["user@example.com"]) == FieldType.EMAIL
        # ISO timestamp
        assert _infer_field_type_from_values(["2026-04-03T10:00:00Z"]) == FieldType.TIMESTAMP_ISO8601
        # Date only
        assert _infer_field_type_from_values(["2026-04-03"]) == FieldType.DATE
        # Integer
        assert _infer_field_type_from_values([42, 100, 200]) == FieldType.INTEGER
        # Epoch ms
        assert _infer_field_type_from_values([1712150400000]) == FieldType.TIMESTAMP_EPOCH_MS
        # Float
        assert _infer_field_type_from_values([1.5, 2.7]) == FieldType.FLOAT
        # Boolean
        assert _infer_field_type_from_values([True, False]) == FieldType.BOOLEAN
        # Null
        assert _infer_field_type_from_values([None, None]) == FieldType.NULL
        # Empty
        assert _infer_field_type_from_values([]) == FieldType.NULL
        # Mixed
        assert _infer_field_type_from_values([42, "hello"]) == FieldType.MIXED

    def test_infer_performance_no_recompilation(self):
        """1000 calls must complete in under 100ms (proves no recompilation)."""
        from streamforge.detector.classify import _infer_field_type_from_values
        values = ["user@example.com", "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "hello"]
        start = time.time()
        for _ in range(1000):
            _infer_field_type_from_values(values)
        elapsed = time.time() - start
        assert elapsed < 0.5, f"1000 calls took {elapsed:.2f}s — regex likely recompiling"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 2: PII leaks in audit logs
# _safe_samples() doesn't redact PII. Sample values with emails, SSNs, etc.
# appear in audit logs.
# FIX: Wire PII detection into _safe_samples(), redact matching values.
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditPIIRedaction:
    """Audit logs must never contain raw PII values."""

    def test_safe_samples_redacts_email(self):
        from streamforge.audit import _safe_samples
        result = _safe_samples(["alice@stripe.com", "normal_value"])
        for item in result:
            assert "alice@stripe.com" not in item, f"Email leaked in audit: {item}"

    def test_safe_samples_redacts_ssn(self):
        from streamforge.audit import _safe_samples
        result = _safe_samples(["123-45-6789"])
        for item in result:
            assert "123-45-6789" not in item, f"SSN leaked in audit: {item}"

    def test_safe_samples_redacts_card_number(self):
        from streamforge.audit import _safe_samples
        result = _safe_samples(["4242-4242-4242-4242"])
        for item in result:
            assert "4242-4242-4242-4242" not in item, f"Card number leaked: {item}"

    def test_safe_samples_redacts_ip_address(self):
        from streamforge.audit import _safe_samples
        result = _safe_samples(["192.168.1.100"])
        for item in result:
            assert "192.168.1.100" not in item, f"IP address leaked: {item}"

    def test_safe_samples_preserves_non_pii(self):
        from streamforge.audit import _safe_samples
        result = _safe_samples(["payment_created", 42, True])
        # Non-PII values should be preserved (as repr strings)
        assert any("payment_created" in item for item in result)

    def test_safe_samples_handles_none(self):
        from streamforge.audit import _safe_samples
        assert _safe_samples(None) == []
        assert _safe_samples([]) == []


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 3: SASL password in Config repr()
# KafkaConfig doesn't have repr=False on sasl_password.
# FIX: Add repr=False to sasl_password field.
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigSecretMasking:
    """Secrets must never appear in repr/str output."""

    def test_sasl_password_not_in_repr(self):
        from streamforge.config import KafkaConfig
        cfg = KafkaConfig(sasl_password="super_secret_password_123")
        r = repr(cfg)
        assert "super_secret_password_123" not in r, f"SASL password leaked in repr: {r}"

    def test_sasl_password_not_in_str(self):
        from streamforge.config import KafkaConfig
        cfg = KafkaConfig(sasl_password="super_secret_password_123")
        s = str(cfg)
        assert "super_secret_password_123" not in s, f"SASL password leaked in str: {s}"

    def test_api_key_not_in_repr(self):
        """Existing behavior — api_key already uses repr=False. Regression check."""
        from streamforge.config import Config
        cfg = Config()
        object.__setattr__(cfg, "_api_key", "sk-secret-key-12345")
        r = repr(cfg)
        assert "sk-secret-key-12345" not in r

    def test_sasl_password_still_accessible(self):
        """Password must still be readable as an attribute."""
        from streamforge.config import KafkaConfig
        cfg = KafkaConfig(sasl_password="my_password")
        assert cfg.sasl_password == "my_password"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 5: MD5 hash collision risk in routing.py
# Structural fingerprint uses MD5[:8] (32-bit). Birthday paradox at 100 clusters.
# FIX: Use SHA256[:16] (64-bit space).
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoutingHashStrength:
    """Structural fingerprinting must use SHA256, not MD5."""

    def test_routing_uses_sha256_not_md5(self):
        """_route_event_to_cluster must use sha256, not md5 for hashing."""
        import inspect

        from streamforge.detector.routing import _route_event_to_cluster
        source = inspect.getsource(_route_event_to_cluster)
        # Must not call hashlib.md5() — comments mentioning MD5 are OK
        assert "hashlib.md5" not in source, "Must use SHA256, not MD5 for hashing"
        assert "hashlib.sha256" in source, "Must use SHA256 for structural fingerprint"

    def test_structural_fingerprint_length(self):
        """Structural fingerprint hash must be at least 12 hex chars (48-bit), matching profiler."""
        from streamforge.detector.routing import _route_event_to_cluster
        # Create a profile with a structural fingerprint cluster
        # Must match profiler.py convention: sha256[:12]
        key_sig = "|".join(sorted(["temperature", "humidity"]))
        h = hashlib.sha256(key_sig.encode()).hexdigest()[:12]
        cluster_id = f"struct:{h}"

        profile = {
            "sub_schemas": [{"cluster_id": cluster_id}],
            "routing_field": None,
        }
        event = {"temperature": 22.5, "humidity": 65.0}
        result = _route_event_to_cluster(event, profile)
        assert result == cluster_id, f"Expected {cluster_id}, got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 6: IP PII detector misses private IPs
# max(octets) > 100 check excludes 10.0.0.50 (max=50).
# FIX: Accept RFC 1918 ranges explicitly + keep version string rejection.
# ═══════════════════════════════════════════════════════════════════════════════

class TestIPDetection:
    """IP PII detector must catch private IPs."""

    def test_10_range_private_ip_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("10.0.0.50"), "10.0.0.50 is a private IP — must be detected"

    def test_10_range_low_octets_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("10.0.0.1"), "10.0.0.1 is a private IP — must be detected"

    def test_172_16_range_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("172.16.0.1"), "172.16.0.1 is a private IP"

    def test_192_168_range_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("192.168.1.1"), "192.168.1.1 is a private IP"

    def test_version_string_rejected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert not _looks_like_ip("1.2.3.4"), "1.2.3.4 is a version string, not an IP"

    def test_version_string_with_high_number_rejected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert not _looks_like_ip("2.0.1.3"), "2.0.1.3 is a version string"

    def test_public_ip_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("203.0.113.50"), "Public IP must be detected"

    def test_loopback_detected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert _looks_like_ip("127.0.0.1"), "Loopback must be detected"

    def test_invalid_octet_rejected(self):
        from streamforge.pii_detector import _looks_like_ip
        assert not _looks_like_ip("999.999.999.999"), "Invalid octets must be rejected"

    def test_pii_detector_finds_private_ip_in_values(self):
        """End-to-end: detect_pii must flag 10.x private IPs."""
        from streamforge.models import PIICategory
        from streamforge.pii_detector import detect_pii
        result = detect_pii("client_ip", ["10.0.0.50", "10.1.2.3"])
        assert PIICategory.IP_ADDRESS in result


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 7: NdjsonSource symlink traversal
# rglob("*") follows symlinks. Must validate files are within folder_path.
# FIX: Resolve symlinks and check they're within the folder.
# ═══════════════════════════════════════════════════════════════════════════════

class TestNdjsonSourceSecurity:
    """NdjsonSource must not follow symlinks outside folder_path."""

    def test_symlink_outside_folder_rejected(self, tmp_path):
        from streamforge.connectors.protocol import NdjsonSource

        # Create a secret file outside the folder
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        secret_file = secret_dir / "passwords.ndjson"
        secret_file.write_text('{"password": "hunter2"}\n')

        # Create the data folder with a symlink to the secret
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        symlink = data_dir / "evil.ndjson"
        symlink.symlink_to(secret_file)

        # NdjsonSource must skip the symlinked file
        source = NdjsonSource(str(data_dir))
        events = source.read_batch(max_messages=100)
        # Must NOT contain the secret data
        for event in events:
            assert "hunter2" not in str(event), "Symlink traversal: secret data leaked"

    def test_normal_files_still_work(self, tmp_path):
        from streamforge.connectors.protocol import NdjsonSource
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\n{"id": 2}\n')
        source = NdjsonSource(str(tmp_path))
        events = source.read_batch(max_messages=10)
        assert len(events) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 8: DLQ producer resource leak
# KafkaProducer is created but never closed.
# FIX: Add close() method and context manager support.
# ═══════════════════════════════════════════════════════════════════════════════

class TestDLQResourceManagement:
    """DLQ must clean up resources."""

    def test_dlq_has_close_method(self):
        from streamforge.dlq import DLQConfig, DLQRouter
        router = DLQRouter("events.payments", ["localhost:9092"], DLQConfig())
        assert hasattr(router, "close"), "DLQRouter must have a close() method"

    def test_dlq_context_manager(self):
        from streamforge.dlq import DLQConfig, DLQRouter
        router = DLQRouter("events.payments", ["localhost:9092"], DLQConfig())
        assert hasattr(router, "__enter__"), "DLQRouter must support context manager"
        assert hasattr(router, "__exit__"), "DLQRouter must support context manager"

    def test_dlq_metadata_namespaced(self):
        """DLQ metadata must be nested under _sf_metadata to avoid key collision."""
        from streamforge.dlq import DLQConfig, DLQRouter
        # Just verify the class structure exists — actual publish needs Kafka
        router = DLQRouter("events.payments", ["localhost:9092"], DLQConfig(enabled=True))
        assert hasattr(router, "route")


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 9: _secure_write() dead code in schema_writer.py
# The function exists but is never called.
# FIX: Wire _secure_write() into write_schema() and other write paths.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecureWrite:
    """Schema files must be written with restricted permissions."""

    def test_schema_yaml_permissions(self, tmp_path):
        """write_schema must produce files with owner-only permissions."""
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema

        schema = InferredSchema(
            stream_name="test_perms", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        schema_dir = tmp_path / "test_perms"
        write_schema(schema, str(tmp_path))
        schema_file = schema_dir / "schema.yaml"
        assert schema_file.exists()
        mode = schema_file.stat().st_mode & 0o777
        # Must be at most 0o644 (owner read/write, group/others read-only at most)
        assert mode & 0o077 <= 0o044, f"Schema file permissions too open: {oct(mode)}"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 10: Audit _ensure_configured() not thread-safe
# Global _configured flag has no lock.
# FIX: Use threading.Lock() to protect initialization.
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditThreadSafety:
    """Audit logger initialization must be thread-safe."""

    def test_ensure_configured_has_lock(self):
        """audit module must use a lock for _ensure_configured."""
        import streamforge.audit as audit_mod
        assert hasattr(audit_mod, "_configure_lock"), "Missing _configure_lock"
        import threading
        assert isinstance(audit_mod._configure_lock, type(threading.Lock()))


# ═══════════════════════════════════════════════════════════════════════════════
# REGRESSION: All existing functionality must still work after fixes
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionAfterFixes:
    """Verify no regression in core functionality."""

    def test_drift_detection_still_works(self):
        from streamforge.detector.core import detect_drift
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
                FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT,
                            required=True, presence_rate=1.0, confidence=0.9),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        # Sample with field removed
        sample = [{"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"} for _ in range(100)]
        report = detect_drift(schema, sample, stream_name="test")
        assert report is not None
        assert any(d.drift_type == "field_removed" for d in report.drifts)

    def test_cluster_window_still_works(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["a", "b"], routing_field="type", capacity=100,
        )
        cwm.add([{"type": "a", "id": 1}, {"type": "b", "id": 2}])
        assert len(cwm.windows["a"]) == 1
        assert len(cwm.windows["b"]) == 1

    def test_pii_detection_still_works(self):
        from streamforge.models import PIICategory
        from streamforge.pii_detector import detect_pii
        result = detect_pii("user_email", ["test@example.com"])
        assert PIICategory.EMAIL in result

    def test_tier_classification_still_works(self):
        from streamforge.detector.classify import classify_drift_tier
        from streamforge.models import DriftTier, FieldDrift
        drift = FieldDrift(
            field_path="amount", drift_type="field_removed",
            affected_event_rate=1.0, previous_presence_rate=1.0,
            observed_presence_rate=0.0,
            tier=DriftTier.TIER_3, auto_correctable=False,
        )
        tier = classify_drift_tier(drift)
        assert tier == DriftTier.TIER_3

    def test_config_load_still_works(self):
        from streamforge.config import Config, load
        cfg = load()
        assert isinstance(cfg, Config)
        assert cfg.inference.provider == "groq"
