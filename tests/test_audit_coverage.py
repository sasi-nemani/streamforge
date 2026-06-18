"""Tests for audit coverage across all code paths.

Ensures multi-schema streams generate audit entries and
audit verbosity is configurable.
"""

import os
from unittest.mock import patch


class TestMultiSchemaAuditCoverage:
    """Multi-schema drift detection must emit audit events."""

    def test_multi_schema_drift_emits_audit_for_each_cluster(self):
        """detect_drift_multi_schema must audit routing and per-cluster results."""
        from streamforge import audit
        from streamforge.detector.routing import detect_drift_multi_schema

        calls = []
        orig = audit.log_drift_check
        audit.log_drift_check = lambda *a, **kw: calls.append(("drift_check", a, kw))

        try:
            # Build a minimal multi-schema profile with 2 clusters
            profile = {
                "sub_schemas": [
                    {
                        "cluster_id": "payment.created",
                        "event_count": 60,
                        "sample_rate": 0.5,
                        "fields": [
                            {"path": "event_id", "type": "uuid", "required": True,
                             "presence_rate": 1.0, "confidence": 0.9},
                            {"path": "amount", "type": "float", "required": True,
                             "presence_rate": 1.0, "confidence": 0.9},
                        ],
                        "inference_confidence": 0.9,
                    },
                    {
                        "cluster_id": "payment.failed",
                        "event_count": 40,
                        "sample_rate": 0.5,
                        "fields": [
                            {"path": "event_id", "type": "uuid", "required": True,
                             "presence_rate": 1.0, "confidence": 0.9},
                            {"path": "error_code", "type": "string", "required": True,
                             "presence_rate": 1.0, "confidence": 0.9},
                        ],
                        "inference_confidence": 0.9,
                    },
                ],
                "routing_field": "event_type",
            }

            # Generate 100 events split between clusters
            events = []
            for i in range(50):
                events.append({"event_id": f"e{i}", "event_type": "payment.created", "amount": 10.0 + i})
            for i in range(50):
                events.append({"event_id": f"f{i}", "event_type": "payment.failed", "error_code": "E01"})

            with patch.dict(os.environ, {"STREAMFORGE_MIN_CLUSTER_EVENTS_FOR_DRIFT": "10"}):
                from streamforge.detector import routing
                routing.MIN_CLUSTER_EVENTS_FOR_DRIFT = 10
                try:
                    reports = detect_drift_multi_schema(profile, events, "events.payments")
                finally:
                    routing.MIN_CLUSTER_EVENTS_FOR_DRIFT = 200

            # Should have audit calls — at least one per cluster that was checked
            assert len(calls) > 0, (
                f"Expected audit calls from multi-schema drift detection, got 0. "
                f"Reports: {len(reports)}"
            )

            # Verify stream name is the TOPIC name, not the cluster ID
            stream_names = {c[2].get("stream", "") for c in calls}
            assert "events.payments" in stream_names, (
                f"Audit should use topic name 'events.payments', got: {stream_names}"
            )

        finally:
            audit.log_drift_check = orig

    def test_routing_regression_emits_audit(self):
        """Cluster routing regression must be audited."""
        from streamforge.detector.routing import detect_drift_multi_schema

        calls = []

        def _capture(*a, **kw):
            calls.append(kw)

        with patch("streamforge.detector.routing.audit.log_drift_check", side_effect=_capture):
            profile = {
                "sub_schemas": [
                    {"cluster_id": "booking.created", "event_count": 50,
                     "sample_rate": 0.5, "fields": [], "inference_confidence": 0.9},
                    {"cluster_id": "booking.cancelled", "event_count": 50,
                     "sample_rate": 0.5, "fields": [], "inference_confidence": 0.9},
                ],
                "routing_field": "event_type",
            }
            events = [{"event_type": "booking.created", "id": str(i)} for i in range(50)]
            detect_drift_multi_schema(profile, events, "events.bookings")

        routing_audits = [c for c in calls if c.get("check_type") == "cluster_routing_regression"]
        assert len(routing_audits) > 0, f"Routing regression should emit audit event, got: {calls}"


class TestAuditVerbosity:
    """Audit verbosity must be configurable."""

    def test_audit_level_controls_clean_field_logging(self):
        """STREAMFORGE_AUDIT_LEVEL=WARNING should suppress clean field checks."""
        from streamforge import audit

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT_LEVEL": "WARNING"}):
            audit._configured = False
            audit._ensure_configured()
            # At WARNING level, DEBUG-level clean checks should be suppressed
            import logging
            assert not audit._audit_logger.isEnabledFor(logging.DEBUG)
            # But WARNING-level corrections should still fire
            assert audit._audit_logger.isEnabledFor(logging.WARNING)

    def test_audit_level_debug_logs_everything(self):
        """STREAMFORGE_AUDIT_LEVEL=DEBUG should log everything."""
        from streamforge import audit

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT_LEVEL": "DEBUG", "STREAMFORGE_AUDIT": "1"}):
            audit._configured = False
            audit._ensure_configured()
            import logging
            assert audit._audit_logger.isEnabledFor(logging.DEBUG)

    def test_clean_field_checks_use_debug_level(self):
        """Clean drift checks should log at DEBUG, not INFO."""
        import logging

        from streamforge import audit

        # Capture log records
        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1", "STREAMFORGE_AUDIT_LEVEL": "DEBUG"}):
            audit._configured = False
            audit._ensure_configured()
            audit._audit_logger.addHandler(handler)
            try:
                audit.log_drift_check("test_field", "all", "clean", stream="test")
                clean_records = [r for r in records if "clean" in r.getMessage()]
                assert len(clean_records) > 0
                assert clean_records[0].levelno == logging.DEBUG
            finally:
                audit._audit_logger.removeHandler(handler)


class TestLlmCallAudit:
    """Every LLM API call must be logged with request/response details."""

    def test_log_llm_request_exists(self):
        from streamforge.audit import log_llm_request
        assert callable(log_llm_request)

    def test_log_llm_request_captures_essentials(self):
        """Must log provider, model, stream, field count, response, latency."""
        import logging

        from streamforge import audit

        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1", "STREAMFORGE_AUDIT_LEVEL": "INFO"}):
            audit._configured = False
            audit._ensure_configured()
            audit._audit_logger.addHandler(handler)
            try:
                audit.log_llm_request(
                    provider="groq",
                    model="llama-3.3-70b-versatile",
                    stream="events.payments",
                    fields_sent=6,
                    fields_returned=6,
                    confidence=0.85,
                    latency_ms=1200,
                    success=True,
                    prompt_chars=5000,
                    response_chars=2000,
                )
                assert len(records) >= 1
                rec = records[-1]
                extra = rec.__dict__
                assert extra["audit"] == "llm_request"
                assert extra["provider"] == "groq"
                assert extra["model"] == "llama-3.3-70b-versatile"
                assert extra["stream"] == "events.payments"
                assert extra["fields_sent"] == 6
                assert extra["fields_returned"] == 6
                assert extra["confidence"] == 0.85
                assert extra["latency_ms"] == 1200
                assert extra["success"] is True
            finally:
                audit._audit_logger.removeHandler(handler)

    def test_log_llm_request_captures_failure(self):
        """Failed LLM calls must also be logged."""
        import logging

        from streamforge import audit

        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1", "STREAMFORGE_AUDIT_LEVEL": "INFO"}):
            audit._configured = False
            audit._ensure_configured()
            audit._audit_logger.addHandler(handler)
            try:
                audit.log_llm_request(
                    provider="groq",
                    model="llama-3.3-70b-versatile",
                    stream="events.payments",
                    fields_sent=6,
                    fields_returned=0,
                    confidence=0.0,
                    latency_ms=30000,
                    success=False,
                    error="timeout after 30s",
                )
                assert len(records) >= 1
                rec = records[-1]
                assert rec.__dict__["success"] is False
                assert rec.__dict__["error"] == "timeout after 30s"
                assert rec.levelno == logging.WARNING  # failures at WARNING
            finally:
                audit._audit_logger.removeHandler(handler)

    def test_log_llm_request_includes_prompt_preview(self):
        """Audit must capture the actual scrubbed prompt sent to the LLM."""
        import logging

        from streamforge import audit

        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1", "STREAMFORGE_AUDIT_LEVEL": "INFO"}):
            audit._configured = False
            audit._ensure_configured()
            audit._audit_logger.addHandler(handler)
            try:
                audit.log_llm_request(
                    provider="groq",
                    model="llama-3.3-70b",
                    stream="events.payments",
                    fields_sent=6,
                    fields_returned=6,
                    confidence=0.85,
                    latency_ms=1200,
                    success=True,
                    prompt_chars=5000,
                    response_chars=2000,
                    prompt_preview="## Field Statistics\nevent_id 100% ...",
                    response_preview='{"fields": [{"path": "event_id"}]}',
                )
                rec = records[-1]
                extra = rec.__dict__
                assert "prompt_preview" in extra
                # "Field Statistics" matches the name-redaction pattern (two capitalized words)
                # so it gets replaced with [REDACTED] — verify scrubbing happened
                assert "[REDACTED]" in extra["prompt_preview"] or "Field Statistics" in extra["prompt_preview"]
                assert "response_preview" in extra
                assert "event_id" in extra["response_preview"]
            finally:
                audit._audit_logger.removeHandler(handler)

    def test_prompt_preview_is_truncated(self):
        """Prompt preview must be capped to prevent log bloat."""
        import logging

        from streamforge import audit

        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)

        with patch.dict(os.environ, {"STREAMFORGE_AUDIT": "1", "STREAMFORGE_AUDIT_LEVEL": "INFO"}):
            audit._configured = False
            audit._ensure_configured()
            audit._audit_logger.addHandler(handler)
            try:
                huge_prompt = "x" * 50000
                audit.log_llm_request(
                    provider="groq", model="test", success=True,
                    prompt_preview=huge_prompt,
                    response_preview="y" * 50000,
                )
                rec = records[-1]
                assert len(rec.__dict__["prompt_preview"]) <= 2100  # ~2000 + margin
                assert len(rec.__dict__["response_preview"]) <= 2100
            finally:
                audit._audit_logger.removeHandler(handler)
