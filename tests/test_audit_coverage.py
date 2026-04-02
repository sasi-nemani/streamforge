"""Tests for audit coverage across all code paths.

Ensures multi-schema streams generate audit entries and
audit verbosity is configurable.
"""

import os
from unittest.mock import patch

import pytest


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
            reports = detect_drift_multi_schema(profile, events, "events.bookings")

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
        from streamforge import audit
        import logging

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
