"""
tests/test_fix_guidance.py — Phase 2: Tests for proposed_correction on field_removed/type_changed
and '### How to fix' section in format_drift_detail.

TDD cycle: these tests are written FIRST and must FAIL before implementation.
"""
from streamforge.drift_detector import detect_drift
from streamforge.models import (
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    InferredSchema,
)
from streamforge.report_writer import format_drift_detail

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_schema(fields: list[FieldSchema]) -> InferredSchema:
    return InferredSchema(
        stream_name="test.stream",
        inferred_at="2026-01-01T00:00:00Z",
        event_count_sampled=20,
        fields=fields,
        inference_model="test",
        inference_confidence=0.9,
    )


def _schema_with_amount_and_timestamp() -> InferredSchema:
    return _make_schema([
        FieldSchema(name="event_id", path="event_id", field_type=FieldType.STRING, presence_rate=1.0),
        FieldSchema(name="timestamp", path="timestamp", field_type=FieldType.TIMESTAMP_EPOCH_MS, presence_rate=1.0),
        FieldSchema(name="amount", path="amount", field_type=FieldType.FLOAT, presence_rate=1.0, required=True),
    ])


# ── Phase 2a: field_removed proposed_correction ────────────────────────────────

def test_field_removed_has_proposed_correction():
    """field_removed drift MUST have a non-empty proposed_correction."""
    baseline = _schema_with_amount_and_timestamp()
    # Sample missing 'amount' entirely — triggers field_removed
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None, "Expected drift report"
    removed = [d for d in report.drifts if d.drift_type == "field_removed" and d.field_path == "amount"]
    assert len(removed) >= 1, "Expected field_removed drift for 'amount'"
    drift = removed[0]
    assert drift.proposed_correction is not None, "field_removed must have proposed_correction"
    assert drift.proposed_correction.strip() != "", "proposed_correction must not be empty"


def test_field_removed_correction_mentions_field_name():
    """field_removed correction must mention the field path."""
    baseline = _schema_with_amount_and_timestamp()
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    removed = [d for d in report.drifts if d.drift_type == "field_removed" and d.field_path == "amount"]
    assert len(removed) >= 1
    drift = removed[0]
    assert "amount" in drift.proposed_correction, (
        "field_removed correction must mention the field path 'amount'"
    )


def test_field_removed_correction_confidence():
    """field_removed correction must have correction_confidence set."""
    baseline = _schema_with_amount_and_timestamp()
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": 1772589500000 + i}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    removed = [d for d in report.drifts if d.drift_type == "field_removed" and d.field_path == "amount"]
    assert len(removed) >= 1
    drift = removed[0]
    assert drift.correction_confidence is not None, "field_removed must set correction_confidence"
    assert 0.0 < drift.correction_confidence <= 1.0


# ── Phase 2b: type_changed proposed_correction ────────────────────────────────

def test_type_changed_has_proposed_correction():
    """type_changed drift MUST have a non-empty proposed_correction."""
    baseline = _schema_with_amount_and_timestamp()
    # New sample has ISO timestamp — triggers type_changed on 'timestamp'
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": "2026-01-01T10:00:00Z", "amount": float(i)}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None, "Expected drift report"
    type_drifts = [d for d in report.drifts if d.drift_type == "type_changed" and d.field_path == "timestamp"]
    assert len(type_drifts) >= 1, "Expected type_changed drift for 'timestamp'"
    drift = type_drifts[0]
    assert drift.proposed_correction is not None, "type_changed must have proposed_correction"
    assert drift.proposed_correction.strip() != "", "proposed_correction must not be empty"


def test_type_changed_correction_includes_python_example():
    """type_changed correction MUST include a Python code example."""
    baseline = _schema_with_amount_and_timestamp()
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": "2026-01-01T10:00:00Z", "amount": float(i)}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    type_drifts = [d for d in report.drifts if d.drift_type == "type_changed" and d.field_path == "timestamp"]
    assert len(type_drifts) >= 1
    drift = type_drifts[0]
    assert drift.proposed_correction is not None
    assert "Python" in drift.proposed_correction or "python" in drift.proposed_correction.lower(), (
        "type_changed correction must include a Python example"
    )


def test_type_changed_correction_includes_java_example():
    """type_changed correction MUST include a Java code example."""
    baseline = _schema_with_amount_and_timestamp()
    new_sample = [
        {"event_id": f"id-{i}", "timestamp": "2026-01-01T10:00:00Z", "amount": float(i)}
        for i in range(1, 21)
    ]
    report = detect_drift(baseline, new_sample, "test.stream")
    assert report is not None
    type_drifts = [d for d in report.drifts if d.drift_type == "type_changed" and d.field_path == "timestamp"]
    assert len(type_drifts) >= 1
    drift = type_drifts[0]
    assert drift.proposed_correction is not None
    assert "Java" in drift.proposed_correction or "java" in drift.proposed_correction.lower(), (
        "type_changed correction must include a Java example"
    )


# ── Phase 2c: format_drift_detail always has '### How to fix' ─────────────────

def test_report_always_has_how_to_fix_section():
    """format_drift_detail output MUST contain '### How to fix'."""
    drift = FieldDrift(
        field_path="amount",
        drift_type="field_removed",
        previous_presence_rate=0.98,
        observed_presence_rate=0.0,
        affected_event_rate=1.0,
        tier=DriftTier.TIER_3,
        auto_correctable=False,
        proposed_correction=(
            "`amount` was removed by the producer.\n"
            "Options:\n"
            "  1. Pin consumer to last version\n"
            "  2. Python: value = event.get('amount')\n"
            "  3. Java: Object value = event.getOrDefault(\"amount\", null);\n"
        ),
        correction_confidence=0.9,
    )
    output = format_drift_detail(drift)
    assert "### How to fix" in output, (
        "format_drift_detail must always include '### How to fix' section"
    )


def test_report_how_to_fix_contains_correction_when_present():
    """When proposed_correction is set, it must appear inside '### How to fix'."""
    correction_text = "Do this specific thing to fix it"
    drift = FieldDrift(
        field_path="user.email",
        drift_type="type_changed",
        previous_type=FieldType.STRING,
        observed_type=FieldType.INTEGER,
        affected_event_rate=0.5,
        tier=DriftTier.TIER_3,
        auto_correctable=False,
        proposed_correction=correction_text,
        correction_confidence=0.85,
    )
    output = format_drift_detail(drift)
    assert "### How to fix" in output
    # The correction text must appear after the How to fix header
    how_to_fix_idx = output.index("### How to fix")
    section_after = output[how_to_fix_idx:]
    assert correction_text in section_after, (
        "proposed_correction must be rendered inside '### How to fix' section"
    )


def test_report_how_to_fix_not_empty_when_no_specific_correction():
    """'### How to fix' section MUST have content even when proposed_correction is None."""
    drift = FieldDrift(
        field_path="some.field",
        drift_type="presence_drop",
        previous_presence_rate=0.9,
        observed_presence_rate=0.4,
        affected_event_rate=0.5,
        tier=DriftTier.TIER_2,
        auto_correctable=False,
        proposed_correction=None,
    )
    output = format_drift_detail(drift)
    assert "### How to fix" in output
    how_to_fix_idx = output.index("### How to fix")
    section_after = output[how_to_fix_idx + len("### How to fix"):].strip()
    assert len(section_after) > 10, (
        "'### How to fix' section must have fallback content when proposed_correction is None"
    )
