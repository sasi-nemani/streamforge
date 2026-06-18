"""Explainability: every statistical drift carries the evidence that fired it."""
from __future__ import annotations

from streamforge.detector.core import detect_drift
from streamforge.models import FieldSchema, FieldType, InferredSchema
from streamforge.report_writer import format_evidence


def _baseline(fields: list[FieldSchema]) -> InferredSchema:
    return InferredSchema(
        stream_name="t",
        version="1.0.0",
        inferred_at="2026-01-01T00:00:00Z",
        event_count_sampled=100,
        fields=fields,
        inference_model="test",
        inference_confidence=1.0,
    )


def test_type_change_carries_chi_squared_evidence():
    baseline = _baseline([
        FieldSchema(name="amount", path="amount", field_type=FieldType.INTEGER),
    ])
    # 60 events: half integer, half string → a real type change, large sample.
    sample = [{"amount": i} for i in range(30)] + [{"amount": f"{i}"} for i in range(30)]
    report = detect_drift(baseline, sample, "t")
    assert report is not None
    drift = next(d for d in report.drifts if d.drift_type == "type_changed")
    assert drift.test_name == "chi_squared"
    assert drift.p_value is not None
    assert drift.effect_size is not None
    # And it renders into a human-readable evidence line.
    rendered = format_evidence(drift)
    assert "chi-squared" in rendered
    assert "effect size" in rendered


def test_presence_drop_carries_binomial_evidence():
    baseline = _baseline([
        FieldSchema(name="region", path="region", field_type=FieldType.STRING, presence_rate=1.0),
    ])
    # Field present in only half of a large sample → presence drop via z-test.
    sample = [{"region": "EU"} for _ in range(30)] + [{} for _ in range(30)]
    report = detect_drift(baseline, sample, "t")
    assert report is not None
    drift = next(d for d in report.drifts if "presence" in d.drift_type or d.drift_type == "field_removed")
    assert drift.test_name == "binomial_z"
    assert drift.p_value is not None


def test_heuristic_drift_has_name_but_no_pvalue():
    """Enum/PII drift records the test name for explainability but no p-value."""
    baseline = _baseline([
        FieldSchema(
            name="status", path="status", field_type=FieldType.STRING,
            enum_values=["A", "B"],
        ),
    ])
    sample = [{"status": "A"} for _ in range(20)] + [{"status": "NOVEL"} for _ in range(20)]
    report = detect_drift(baseline, sample, "t")
    assert report is not None
    enum_drift = next(d for d in report.drifts if d.drift_type == "enum_changed")
    assert enum_drift.test_name == "enum_threshold"
    assert enum_drift.p_value is None
    # Renders without a p-value, just the heuristic label.
    assert "heuristic" in format_evidence(enum_drift)


def test_no_evidence_renders_empty():
    """A drift with no recorded test yields an empty evidence string."""
    from streamforge.models import DriftTier, FieldDrift

    drift = FieldDrift(
        field_path="x", drift_type="field_added", affected_event_rate=0.5,
        tier=DriftTier.TIER_1, auto_correctable=False,
    )
    assert format_evidence(drift) == ""
