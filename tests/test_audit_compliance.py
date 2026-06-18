"""Tests for audit log compliance: rotation, syslog, extended PII redaction."""
import logging
import logging.handlers


class TestRotatingFileHandler:
    """Audit file handler must rotate at configurable size."""

    def test_rotating_handler_configured(self, tmp_path, monkeypatch):
        """When STREAMFORGE_AUDIT_FILE is set, handler must be RotatingFileHandler."""
        import streamforge.audit as audit_mod
        # Reset audit config state
        audit_mod._configured = False
        audit_mod._audit_logger.handlers.clear()
        monkeypatch.setenv("STREAMFORGE_AUDIT", "1")
        monkeypatch.setenv("STREAMFORGE_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
        monkeypatch.setenv("STREAMFORGE_AUDIT_MAX_BYTES", "10000")
        monkeypatch.setenv("STREAMFORGE_AUDIT_BACKUP_COUNT", "3")
        audit_mod._ensure_configured()
        file_handlers = [
            h for h in audit_mod._audit_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) >= 1, "Must use RotatingFileHandler, not plain FileHandler"
        rh = file_handlers[0]
        assert rh.maxBytes == 10000
        assert rh.backupCount == 3
        # Cleanup
        audit_mod._configured = False
        audit_mod._audit_logger.handlers.clear()


class TestSysLogHandler:
    """Optional syslog forwarding for centralized logging."""

    def test_syslog_handler_added_when_configured(self, monkeypatch):
        import streamforge.audit as audit_mod
        audit_mod._configured = False
        audit_mod._audit_logger.handlers.clear()
        monkeypatch.setenv("STREAMFORGE_AUDIT", "1")
        monkeypatch.setenv("STREAMFORGE_AUDIT_SYSLOG", "localhost:1514")
        audit_mod._ensure_configured()
        syslog_handlers = [
            h for h in audit_mod._audit_logger.handlers
            if isinstance(h, logging.handlers.SysLogHandler)
        ]
        assert len(syslog_handlers) >= 1, "SysLogHandler must be added when SYSLOG env set"
        # Cleanup
        audit_mod._configured = False
        audit_mod._audit_logger.handlers.clear()


class TestExtendedPiiRedaction:
    """PII redaction must cover names, DOB, and addresses."""

    def test_scrub_name_pattern(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("customer John Smith purchased item")
        assert "John Smith" not in result

    def test_scrub_dob_pattern(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("born on 1990-05-15 in Chicago")
        assert "1990-05-15" not in result

    def test_scrub_address_pattern(self):
        from streamforge.audit import _scrub_preview
        result = _scrub_preview("lives at 123 Main St in Springfield")
        assert "123 Main St" not in result
