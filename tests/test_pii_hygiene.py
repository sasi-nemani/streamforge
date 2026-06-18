"""Tests for PII hygiene: audit log scrubbing + secure file permissions."""
import logging
from pathlib import Path


class TestAuditPromptScrubbing:
    """prompt_preview and response_preview must be scrubbed in log_llm_request."""

    def test_scrub_preview_redacts_email(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("Field stats: user_001@streamforge.synthetic has type email")
        assert "@" not in result or "[REDACTED]" in result

    def test_scrub_preview_redacts_ssn(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("SSN field contains 123-45-6789")
        assert "123-45-6789" not in result

    def test_scrub_preview_redacts_card(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("card: 4242 4242 4242 4242")
        assert "4242 4242 4242 4242" not in result

    def test_scrub_preview_redacts_ip(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("client_ip: 198.51.100.42")
        assert "198.51.100.42" not in result

    def test_scrub_preview_preserves_non_pii(self):
        from streamforge.audit import _scrub_preview
        text = "Field event_type has 3 distinct values: payment.created, payment.failed"
        result = _scrub_preview(text)
        assert "payment.created" in result

    def test_scrub_preview_handles_empty(self):
        from streamforge.audit import _scrub_preview
        assert _scrub_preview("") == ""

    def test_log_llm_request_uses_scrubbed_preview(self):
        """Verify log_llm_request passes previews through _scrub_preview."""
        import streamforge.audit as audit_mod
        # Capture what gets logged
        captured = {}
        original_log = audit_mod._audit_logger.log
        def capture_log(level, msg, *args, **kwargs):
            extra = kwargs.get("extra", {})
            captured.update(extra)
        audit_mod._audit_logger.log = capture_log
        audit_mod._configured = True
        audit_mod._audit_logger.setLevel(logging.DEBUG)
        try:
            audit_mod.log_llm_request(
                provider="test", model="test",
                prompt_preview="user alice@test.com typed something",
                response_preview="SSN 123-45-6789 detected",
            )
            assert "alice@test.com" not in captured.get("prompt_preview", "")
            assert "123-45-6789" not in captured.get("response_preview", "")
        finally:
            audit_mod._audit_logger.log = original_log


class TestSecureWriteAllPaths:
    """All schema_writer output files must have restricted permissions."""

    def _check_perms(self, path: Path):
        mode = path.stat().st_mode & 0o777
        assert mode & 0o077 == 0, f"{path.name} has permissions {oct(mode)}, expected owner-only (0o600)"

    def test_json_schema_permissions(self, tmp_path):
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema_with_exports
        schema = InferredSchema(
            stream_name="perm_test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                                required=True, presence_rate=1.0, confidence=0.9)],
            inference_model="test", inference_confidence=0.9,
        )
        write_schema_with_exports(schema, str(tmp_path))
        out = tmp_path / "perm_test"
        self._check_perms(out / "schema.json")
        self._check_perms(out / "schema.avsc")
        self._check_perms(out / "DATA_DICTIONARY.md")

    def test_inference_report_permissions(self, tmp_path):
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_inference_report
        schema = InferredSchema(
            stream_name="perm_test2", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                                required=True, presence_rate=1.0, confidence=0.9)],
            inference_model="test", inference_confidence=0.9,
        )
        write_inference_report(schema, str(tmp_path))
        self._check_perms(tmp_path / "perm_test2" / "inference_report.md")

    def test_samples_permissions(self, tmp_path):
        from streamforge.schema_writer import write_samples
        write_samples([{"id": 1}], str(tmp_path), "perm_test3")
        self._check_perms(tmp_path / "perm_test3" / ".samples" / "latest.json")

    def test_drift_state_permissions(self, tmp_path):
        from streamforge.models import DriftState
        from streamforge.schema_writer import save_drift_state
        state = DriftState(stream_name="test", updated_at="2026-04-03", incidents=[])
        save_drift_state(tmp_path, state)
        self._check_perms(tmp_path / "drift_state.yaml")
