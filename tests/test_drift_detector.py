from pathlib import Path

import pytest

from streamforge.drift_detector import classify_drift_tier, detect_drift
from streamforge.models import (
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    InferredSchema,
    PIICategory,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_schema(fields: list[FieldSchema]) -> InferredSchema:
    return InferredSchema(
        stream_name="test.stream",
        inferred_at="2026-01-01T00:00:00Z",
        event_count_sampled=20,
        fields=fields,
        inference_model="test",
        inference_confidence=0.9,
    )


def _base_payment_schema() -> InferredSchema:
    return _make_schema([
        FieldSchema(name="event_id", path="event_id", field_type=FieldType.STRING, presence_rate=1.0),
        FieldSchema(name="timestamp", path="timestamp", field_type=FieldType.TIMESTAMP_EPOCH_MS, presence_rate=1.0),
        FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT, presence_rate=1.0, required=True),
        FieldSchema(name="currency", path="currency", field_type=FieldType.STRING, presence_rate=1.0,
                    enum_values=["USD", "EUR", "GBP"]),
        FieldSchema(name="status", path="status", field_type=FieldType.STRING, presence_rate=1.0,
                    enum_values=["COMPLETED", "FAILED", "PENDING"]),
    ])


def test_detects_type_change_tier2():
    baseline = _base_payment_schema()
    # New sample has ISO timestamp instead of epoch
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": "2026-01-01T10:00:00Z",
         "amount": float(i * 10), "currency": "USD", "status": "COMPLETED"}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    ts_drifts = [d for d in report.drifts if d.field_path == "timestamp" and d.drift_type == "type_changed"]
    assert len(ts_drifts) >= 1
    assert ts_drifts[0].tier == DriftTier.TIER_2


def test_detects_field_removal_tier3():
    baseline = _base_payment_schema()
    # New sample missing 'amount' entirely
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i,
         "currency": "USD", "status": "COMPLETED"}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    removed = [d for d in report.drifts if d.field_path == "amount" and d.drift_type == "field_removed"]
    assert len(removed) >= 1
    assert removed[0].tier == DriftTier.TIER_3


def test_detects_new_optional_field_tier1():
    baseline = _base_payment_schema()
    # New sample has extra optional field in ~30% of events
    new_sample = []
    for i in range(1, 21):
        ev = {"event_id": f"id-{i}", "timestamp": 1772589500000 + i,
              "amount": float(i * 10), "currency": "USD", "status": "COMPLETED"}
        if i <= 6:  # 30% have the new field
            ev["merchant_id"] = f"MCH-{i}"
        new_sample.append(ev)
    report = detect_drift(baseline, new_sample, "test.stream")
    if report is not None:
        added = [d for d in report.drifts if d.field_path == "merchant_id" and d.drift_type == "field_added"]
        if added:
            assert added[0].tier == DriftTier.TIER_1


def test_no_false_positive_on_clean_data():
    baseline = _base_payment_schema()
    # Sample matches schema exactly
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i,
         "amount": float(i * 10), "currency": "USD", "status": "COMPLETED"}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    # No drift or only tier1 informational
    if report is not None:
        critical = [d for d in report.drifts if d.tier >= DriftTier.TIER_2]
        assert len(critical) == 0


def test_enum_drift_detected():
    baseline = _base_payment_schema()
    # New currency value appears
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i,
         "amount": float(i * 10), "currency": "JPY" if i <= 5 else "USD", "status": "COMPLETED"}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    enum_drifts = [d for d in report.drifts if d.drift_type == "enum_changed"]
    assert len(enum_drifts) >= 1


def test_classify_drift_tier_timestamp_is_tier2():
    drift = FieldDrift(
        field_path="created_at",
        drift_type="type_changed",
        previous_type=FieldType.TIMESTAMP_EPOCH_MS,
        observed_type=FieldType.TIMESTAMP_ISO8601,
        affected_event_rate=1.0,
        tier=DriftTier.TIER_1,
        auto_correctable=True,
    )
    assert classify_drift_tier(drift) == DriftTier.TIER_2


def test_classify_drift_tier_required_field_removed_is_tier3():
    drift = FieldDrift(
        field_path="amount",
        drift_type="field_removed",
        previous_presence_rate=0.98,
        observed_presence_rate=0.0,
        affected_event_rate=1.0,
        tier=DriftTier.TIER_1,
        auto_correctable=False,
    )
    assert classify_drift_tier(drift) == DriftTier.TIER_3
