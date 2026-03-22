"""
Tests for P1/P2 bug fixes identified in the production run REPORT.md.
All tests are written before the fix (RED phase).

Bugs covered:
  P1-1  IoT counter never increments (_type key missing in _iot_event)
  P1-2  Warm-up grace period: first N cycles should not fire drift alerts
  P2-3  new_cluster threshold is configurable (env var)
  P2-4  ticket_number should NOT be classified as passport PII
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# P1-1 — IoT counter bug
# ---------------------------------------------------------------------------

def test_iot_event_has_type_field():
    """_iot_event() must include '_type': 'iot_sensor' so publish() can count it."""
    # Re-import fresh so we don't get cached state
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from demo.feed_all import _iot_event  # type: ignore[import]
    ev = _iot_event()
    assert "_type" in ev, "_iot_event() must include '_type' key for counter routing"
    assert ev["_type"] == "iot_sensor"


def test_iot_publish_increments_counter():
    """Publishing an IoT event must increment _counts['iot_sensor']."""
    from demo import feed_all  # type: ignore[import]
    # Reset counter
    with feed_all._counts_lock:
        feed_all._counts["iot_sensor"] = 0

    fake_producer = mock.MagicMock()
    iot_ev = feed_all._iot_event()
    feed_all.publish(fake_producer, iot_ev)

    assert feed_all._counts["iot_sensor"] == 1, (
        f"Expected _counts['iot_sensor']==1 after publish, got {feed_all._counts['iot_sensor']}"
    )


def test_payment_counter_still_works():
    """Regression: payment counter must still increment after iot fix."""
    from demo import feed_all  # type: ignore[import]
    with feed_all._counts_lock:
        feed_all._counts["payment"] = 0

    fake_producer = mock.MagicMock()
    pay_ev = feed_all._payment_event()
    feed_all.publish(fake_producer, pay_ev)

    assert feed_all._counts["payment"] == 1


# ---------------------------------------------------------------------------
# P1-2 — Warm-up grace period
# ---------------------------------------------------------------------------

def _make_profile_dict(n_clusters: int = 2) -> dict:
    """Minimal profile dict for multi-schema drift tests.

    The cluster_id MUST match the event_type value that appears in events,
    because _route_event_to_cluster checks event[routing_field] against
    the set of known cluster_ids directly.
    """
    sub = []
    for i in range(n_clusters):
        cid = f"type_{i}"  # matches event_type values used in tests
        sub.append({
            "cluster_id": cid,
            "event_count": 200,
            "stream_share": 1.0 / n_clusters,
            "fields": [
                {"path": "id", "field_type": "string", "required": True, "nullable": False,
                 "presence_rate": 1.0, "sample_values": [], "confidence": 0.9,
                 "pii_categories": [], "name": "id"},
                {"path": "event_type", "field_type": "string", "required": True, "nullable": False,
                 "presence_rate": 1.0, "sample_values": [cid], "confidence": 0.9,
                 "pii_categories": [], "name": "event_type",
                 "enum_values": [cid]},
            ],
            "inference_confidence": 0.85,
        })
    return {
        "stream_name": "test.stream",
        "routing_field": "event_type",
        "sub_schemas": sub,
    }


def test_detect_drift_multi_schema_returns_no_reports_on_warmup():
    """
    detect_drift_multi_schema must accept a warmup_cycle flag and return
    an empty list (no alerts) when it is True, even if the sample would
    normally trigger drift.
    """
    from streamforge.drift_detector import detect_drift_multi_schema

    profile = _make_profile_dict(n_clusters=2)
    # Sample that would normally trigger new_cluster (all unknown events)
    sample = [{"event_type": "totally_unknown_type", "id": str(i)} for i in range(100)]

    # Normal call — should detect new_cluster drift
    normal_reports = detect_drift_multi_schema(profile, sample, "test.stream")
    # Some drift expected
    assert len(normal_reports) > 0, "Expected drift without warmup guard"

    # Warmup call — should return empty regardless
    warmup_reports = detect_drift_multi_schema(
        profile, sample, "test.stream", warmup=True
    )
    assert warmup_reports == [], (
        f"Expected no reports during warmup, got {warmup_reports}"
    )


# ---------------------------------------------------------------------------
# P2-3 — new_cluster threshold configurable
# ---------------------------------------------------------------------------

def test_new_cluster_default_threshold_is_0_05():
    """Default new_cluster threshold should be 0.05 (5%)."""
    from streamforge import drift_detector
    threshold = drift_detector._new_cluster_threshold()
    assert threshold == pytest.approx(0.05), (
        f"Default threshold should be 0.05, got {threshold}"
    )


def test_new_cluster_threshold_reads_env_var(monkeypatch: pytest.MonkeyPatch):
    """STREAMFORGE_NEW_CLUSTER_THRESHOLD env var must override the default."""
    monkeypatch.setenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", "0.12")
    # Reload to pick up monkeypatched env
    from streamforge import drift_detector
    threshold = drift_detector._new_cluster_threshold()
    assert threshold == pytest.approx(0.12), (
        f"Expected 0.12 from env var, got {threshold}"
    )


def test_new_cluster_not_fired_below_threshold(monkeypatch: pytest.MonkeyPatch):
    """With threshold=0.20, an 8% unknown rate must NOT trigger new_cluster drift."""
    monkeypatch.setenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", "0.20")

    from streamforge.drift_detector import detect_drift_multi_schema

    profile = _make_profile_dict(n_clusters=1)
    # Mostly known events (type_0) + 8% unknown
    known = [{"event_type": "type_0", "id": str(i)} for i in range(92)]
    unknown = [{"event_type": "unknown_new", "id": str(i)} for i in range(8)]
    sample = known + unknown

    # Must NOT produce new_cluster drift at threshold=0.20 when rate is 8%
    reports = detect_drift_multi_schema(profile, sample, "test.stream")
    drift_types = [
        d.drift_type
        for r in reports
        for d in r.drifts
    ]
    assert "new_cluster" not in drift_types, (
        f"new_cluster should not fire at 8% when threshold is 20%, got: {drift_types}"
    )


# ---------------------------------------------------------------------------
# P2-4 — ticket_number must NOT be passport PII
# ---------------------------------------------------------------------------

def test_ticket_number_not_passport_pii():
    """ticket_number is a booking reference, not a travel document — must not be passport PII."""
    from streamforge.pii_detector import detect_pii
    from streamforge.models import PIICategory

    # A field named ticket_number with a booking-style value
    categories = detect_pii("ticket_number", ["TKT-2345678", "TKT-8901234"])
    assert PIICategory.PASSPORT not in categories, (
        f"ticket_number must not be classified as passport PII, got: {categories}"
    )


def test_passport_number_still_detected():
    """Regression: actual passport_number field must still be detected as PII."""
    from streamforge.pii_detector import detect_pii
    from streamforge.models import PIICategory

    categories = detect_pii("passport_number", ["A1234567", "B9876543"])
    assert PIICategory.PASSPORT in categories
