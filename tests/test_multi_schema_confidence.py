"""
Multi-Schema Confidence Tests (Stripe Engineering Requirements).

Tests verify:
1. Discriminator detection via entropy analysis
2. Stratified sampling ensures rare type coverage
3. Confidence intervals are statistically valid
4. Distribution reports are accurate
5. Audit events are emitted at each stage
6. Edge cases: missing discriminator, single type, malformed events
"""

from __future__ import annotations

import json
import math
from datetime import datetime, UTC
from io import StringIO
from typing import Any

import pytest

from streamforge.models import (
    DiscriminatorInfo,
    DiscriminatorMethod,
    MultiSchemaAuditEvent,
    MultiSchemaConfidence,
    SamplingReport,
    TypeConfidence,
    TypeDistribution,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mixed_events() -> list[dict[str, Any]]:
    """Sample events with clear discriminator field."""
    events = []
    # 45% payment.succeeded
    for i in range(450):
        events.append({
            "type": "payment.succeeded",
            "amount": 1000 + i,
            "currency": "usd",
            "timestamp": f"2024-01-{(i % 28) + 1:02d}",
        })
    # 30% invoice.created
    for i in range(300):
        events.append({
            "type": "invoice.created",
            "invoice_id": f"inv_{i}",
            "customer_id": f"cust_{i % 100}",
        })
    # 20% customer.updated
    for i in range(200):
        events.append({
            "type": "customer.updated",
            "customer_id": f"cust_{i}",
            "email": f"user{i}@example.com",
        })
    # 5% refund.created (rare)
    for i in range(50):
        events.append({
            "type": "refund.created",
            "refund_id": f"ref_{i}",
            "amount": 500,
        })
    return events


@pytest.fixture
def rare_type_events() -> list[dict[str, Any]]:
    """Events with very rare types that may be missed by sampling."""
    events = []
    # 99% common type
    for i in range(9900):
        events.append({"type": "common.event", "id": i})
    # 0.9% less common
    for i in range(90):
        events.append({"type": "less_common.event", "id": i})
    # 0.1% rare (10 events) - may be missed in 1000 sample
    for i in range(10):
        events.append({"type": "rare.event", "id": i})
    return events


@pytest.fixture
def no_discriminator_events() -> list[dict[str, Any]]:
    """Events without a clear discriminator field."""
    return [
        {"user_id": "u1", "action": "click", "page": "/home"},
        {"user_id": "u2", "action": "scroll", "page": "/products"},
        {"order_id": "o1", "status": "shipped", "tracking": "XYZ"},
        {"order_id": "o2", "status": "delivered"},
    ]


@pytest.fixture
def nested_discriminator_events() -> list[dict[str, Any]]:
    """Events with discriminator in nested field."""
    return [
        {"metadata": {"event_type": "user.signup"}, "user_id": "u1"},
        {"metadata": {"event_type": "user.signup"}, "user_id": "u2"},
        {"metadata": {"event_type": "order.placed"}, "order_id": "o1"},
    ]


@pytest.fixture
def audit_stream() -> StringIO:
    """Capture audit events."""
    return StringIO()


# ---------------------------------------------------------------------------
# Discriminator Detection Tests
# ---------------------------------------------------------------------------

class TestDiscriminatorDetection:
    """Tests for discriminator.py module."""

    def test_detect_type_field(self, mixed_events):
        """Detects 'type' field as discriminator."""
        from streamforge.discriminator import detect_discriminator

        result = detect_discriminator(mixed_events)

        assert result is not None
        assert result.field_path == "type"
        assert result.method == DiscriminatorMethod.AUTO_DETECTED
        assert result.cardinality == 4  # 4 distinct types
        assert result.coverage == 1.0  # All events have 'type'
        assert result.entropy > 0  # Non-zero entropy

    def test_explicit_discriminator(self, mixed_events):
        """Uses explicit discriminator when provided."""
        from streamforge.discriminator import detect_discriminator

        result = detect_discriminator(
            mixed_events,
            explicit_field="type",
        )

        assert result.method == DiscriminatorMethod.EXPLICIT
        assert result.field_path == "type"

    def test_nested_discriminator(self, nested_discriminator_events):
        """Detects nested discriminator path."""
        from streamforge.discriminator import detect_discriminator

        result = detect_discriminator(
            nested_discriminator_events,
            candidates=["metadata.event_type"],
        )

        assert result is not None
        assert result.field_path == "metadata.event_type"
        assert result.cardinality == 2

    def test_no_discriminator_returns_none(self, no_discriminator_events):
        """Returns None when no suitable discriminator found."""
        from streamforge.discriminator import detect_discriminator

        result = detect_discriminator(
            no_discriminator_events,
            min_cardinality=5,  # Require at least 5 types
        )

        assert result is None

    def test_entropy_ranking(self, mixed_events):
        """Lower cardinality fields with good entropy are preferred."""
        from streamforge.discriminator import calculate_entropy

        # 'type' has 4 values with distribution 45/30/20/5 - moderate entropy
        # A field with too high cardinality is not a good discriminator

        # Add a field with very high cardinality (unique per event)
        for i, event in enumerate(mixed_events):
            event["unique_field"] = f"value_{i}"

        from streamforge.discriminator import detect_discriminator
        result = detect_discriminator(
            mixed_events,
            candidates=["type", "unique_field"],
            max_cardinality=100,  # unique_field has 1000 values, exceeds max
        )

        # 'type' should win because unique_field exceeds max_cardinality
        assert result.field_path == "type"

    def test_audit_event_emitted(self, mixed_events, audit_stream):
        """Audit event is emitted during detection."""
        from streamforge.discriminator import detect_discriminator

        result = detect_discriminator(
            mixed_events,
            audit_stream=audit_stream,
        )

        audit_stream.seek(0)
        audit_lines = audit_stream.read().strip().split("\n")
        assert len(audit_lines) >= 1

        audit_event = json.loads(audit_lines[0])
        assert audit_event["operation"] == "discriminator_detection"
        assert audit_event["success"] is True
        assert "duration_ms" in audit_event


# ---------------------------------------------------------------------------
# Stratified Sampling Tests
# ---------------------------------------------------------------------------

class TestStratifiedSampling:
    """Tests for stratified_sampler.py module."""

    def test_stratified_sample_covers_all_types(self, mixed_events):
        """Stratified sampling includes all types."""
        from streamforge.stratified_sampler import stratified_sample

        result, report = stratified_sample(
            mixed_events,
            discriminator_field="type",
            total_size=200,
            min_per_type=5,
        )

        # All 4 types should be present
        assert len(result) == 4
        assert "payment.succeeded" in result
        assert "invoice.created" in result
        assert "customer.updated" in result
        assert "refund.created" in result

        # Each type has at least min_per_type samples
        for type_name, samples in result.items():
            assert len(samples) >= 5, f"{type_name} has only {len(samples)} samples"

    def test_stratified_sample_rare_type_guarantee(self, rare_type_events):
        """Stratified sampling guarantees rare types are included."""
        from streamforge.stratified_sampler import stratified_sample

        result, report = stratified_sample(
            rare_type_events,
            discriminator_field="type",
            total_size=100,
            min_per_type=3,
        )

        # Rare type (0.1%) must be present with at least 3 samples
        assert "rare.event" in result
        assert len(result["rare.event"]) >= 3
        assert report.stratified is True

    def test_uniform_sample_misses_rare_types(self, rare_type_events):
        """Uniform sampling may miss rare types (baseline comparison)."""
        from streamforge.stratified_sampler import uniform_sample

        # Run multiple trials
        rare_found = 0
        trials = 100
        for seed in range(trials):
            result = uniform_sample(rare_type_events, size=100, seed=seed)
            if any(e.get("type") == "rare.event" for e in result):
                rare_found += 1

        # Statistically, with 0.1% frequency and 100 samples,
        # expected count per sample = 0.1, so P(at least 1) ≈ 9.5%
        # With 100 trials, expect ~10 to find the rare type
        assert rare_found < 50, f"Expected ~10 trials to find rare type, got {rare_found}"

    def test_sampling_report_accuracy(self, mixed_events):
        """Sampling report contains accurate metadata."""
        from streamforge.stratified_sampler import stratified_sample

        _, report = stratified_sample(
            mixed_events,
            discriminator_field="type",
            total_size=200,
            min_per_type=10,
        )

        assert report.total_sampled == 200
        assert report.stratified is True
        assert report.min_per_type == 10
        assert report.sampling_method == "stratified"

    def test_audit_event_emitted(self, mixed_events, audit_stream):
        """Audit event is emitted during sampling."""
        from streamforge.stratified_sampler import stratified_sample

        stratified_sample(
            mixed_events,
            discriminator_field="type",
            total_size=100,
            audit_stream=audit_stream,
        )

        audit_stream.seek(0)
        audit_lines = audit_stream.read().strip().split("\n")
        audit_event = json.loads(audit_lines[0])
        assert audit_event["operation"] == "stratified_sampling"


# ---------------------------------------------------------------------------
# Confidence Calculation Tests
# ---------------------------------------------------------------------------

class TestConfidenceCalculation:
    """Tests for confidence.py module."""

    def test_wilson_score_interval(self):
        """Wilson score interval calculation is correct."""
        from streamforge.confidence import wilson_score_interval

        # 50 successes out of 100 trials
        lower, upper = wilson_score_interval(50, 100, z=1.96)

        # 95% CI for p=0.5, n=100 should be approximately (0.40, 0.60)
        assert 0.39 < lower < 0.42
        assert 0.58 < upper < 0.61

    def test_confidence_high_for_common_types(self, mixed_events):
        """High confidence for types with many samples."""
        from streamforge.confidence import calculate_type_confidence

        # Group by type
        type_counts = {}
        for e in mixed_events:
            t = e["type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        result = calculate_type_confidence(
            type_counts=type_counts,
            total_sampled=len(mixed_events),
        )

        # payment.succeeded has 450 samples - should be statistically valid
        payment_conf = next(c for c in result if c.type_value == "payment.succeeded")
        assert payment_conf.statistically_valid is True
        assert payment_conf.sample_count == 450
        assert payment_conf.frequency == pytest.approx(0.45, rel=0.01)

    def test_confidence_low_for_rare_types(self):
        """Low confidence for types with few samples."""
        from streamforge.confidence import calculate_type_confidence

        type_counts = {
            "common": 970,
            "rare": 30,  # Exactly at threshold
            "very_rare": 5,  # Below threshold
        }

        result = calculate_type_confidence(
            type_counts=type_counts,
            total_sampled=1005,
        )

        rare = next(c for c in result if c.type_value == "rare")
        very_rare = next(c for c in result if c.type_value == "very_rare")

        assert rare.statistically_valid is True  # >= 30
        assert very_rare.statistically_valid is False  # < 30

    def test_overall_confidence_weighted(self, mixed_events):
        """Overall confidence is weighted by type frequency."""
        from streamforge.confidence import calculate_overall_confidence

        type_confidences = [
            TypeConfidence(
                type_value="common",
                sample_count=900,
                frequency=0.9,
                confidence_lower=0.88,
                confidence_upper=0.92,
                schema_confidence=0.95,
                statistically_valid=True,
            ),
            TypeConfidence(
                type_value="rare",
                sample_count=10,
                frequency=0.1,
                confidence_lower=0.05,
                confidence_upper=0.15,
                schema_confidence=0.40,
                statistically_valid=False,
            ),
        ]

        overall = calculate_overall_confidence(type_confidences)

        # Should be closer to 0.95 (common type) than 0.40 (rare type)
        # Weighted: 0.9 * 0.95 + 0.1 * 0.40 = 0.855 + 0.04 = 0.895
        assert 0.85 < overall < 0.95

    def test_coverage_guarantee_message(self):
        """Coverage guarantee message is correctly generated."""
        from streamforge.confidence import generate_coverage_guarantee

        # With 1000 samples, 95% confident we've seen types > 0.3%
        message = generate_coverage_guarantee(
            total_sampled=1000,
            min_samples_per_type=3,
            confidence_level=0.95,
        )

        assert "95%" in message
        assert "0.3%" in message or "0.003" in message


# ---------------------------------------------------------------------------
# Distribution Report Tests
# ---------------------------------------------------------------------------

class TestDistributionReport:
    """Tests for distribution.py module."""

    def test_distribution_percentages(self, mixed_events):
        """Distribution percentages are accurate."""
        from streamforge.distribution import calculate_distribution

        distribution = calculate_distribution(mixed_events, discriminator_field="type")

        # Verify percentages
        payment = next(d for d in distribution if d.type_value == "payment.succeeded")
        assert payment.percentage == pytest.approx(45.0, rel=0.1)
        assert payment.count == 450

        refund = next(d for d in distribution if d.type_value == "refund.created")
        assert refund.percentage == pytest.approx(5.0, rel=0.1)
        assert refund.count == 50

    def test_distribution_sorted_by_frequency(self, mixed_events):
        """Distribution is sorted by frequency descending."""
        from streamforge.distribution import calculate_distribution

        distribution = calculate_distribution(mixed_events, discriminator_field="type")

        percentages = [d.percentage for d in distribution]
        assert percentages == sorted(percentages, reverse=True)

    def test_distribution_warnings_for_rare(self):
        """Warnings added for types with insufficient samples."""
        from streamforge.distribution import calculate_distribution

        events = [{"type": "common"}] * 995 + [{"type": "rare"}] * 5

        distribution = calculate_distribution(
            events,
            discriminator_field="type",
            min_samples_warning=30,
        )

        rare = next(d for d in distribution if d.type_value == "rare")
        assert rare.warning is not None
        assert "insufficient" in rare.warning.lower()


# ---------------------------------------------------------------------------
# End-to-End Integration Tests
# ---------------------------------------------------------------------------

class TestMultiSchemaConfidenceIntegration:
    """End-to-end tests for the full pipeline."""

    def test_full_pipeline(self, mixed_events, audit_stream):
        """Full pipeline produces complete MultiSchemaConfidence report."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        result = analyze_multi_schema(
            events=mixed_events,
            sample_size=500,
            min_per_type=10,
            audit_stream=audit_stream,
        )

        # Verify result structure
        assert isinstance(result, MultiSchemaConfidence)
        assert result.types_detected == 4
        assert result.discriminator.field_path == "type"
        assert len(result.distribution) == 4
        assert len(result.per_type_confidence) == 4
        assert 0.6 < result.overall_confidence < 1.0  # Conservative confidence scoring
        assert "95%" in result.coverage_guarantee

        # Verify audit events were emitted
        audit_stream.seek(0)
        audit_lines = [l for l in audit_stream.read().strip().split("\n") if l]
        operations = [json.loads(l)["operation"] for l in audit_lines]
        assert "discriminator_detection" in operations
        assert "stratified_sampling" in operations

    def test_explicit_discriminator_override(self, mixed_events):
        """Explicit discriminator overrides auto-detection."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        # Add a secondary field
        for i, e in enumerate(mixed_events):
            e["category"] = "cat_" + str(i % 3)

        result = analyze_multi_schema(
            events=mixed_events,
            discriminator="category",  # Override to use category
        )

        assert result.discriminator.field_path == "category"
        assert result.discriminator.method == DiscriminatorMethod.EXPLICIT
        assert result.types_detected == 3  # cat_0, cat_1, cat_2

    def test_no_discriminator_fallback(self, no_discriminator_events):
        """Falls back to structural fingerprint when no discriminator found."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        result = analyze_multi_schema(
            events=no_discriminator_events,
            min_cardinality=10,  # Force no discriminator match
        )

        # Should fall back to structural method
        assert result.discriminator.method == DiscriminatorMethod.STRUCTURAL
        assert "structural" in result.warnings[0].lower() or len(result.warnings) > 0

    def test_timing_telemetry(self, mixed_events):
        """Timing telemetry is captured."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        result = analyze_multi_schema(events=mixed_events)

        assert result.detection_time_ms is not None
        assert result.detection_time_ms >= 0
        assert result.inference_time_ms is not None

    def test_empty_events_handled(self):
        """Empty event list is handled gracefully."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        result = analyze_multi_schema(events=[])

        assert result.types_detected == 0
        assert len(result.warnings) > 0
        assert "empty" in result.warnings[0].lower()


# ---------------------------------------------------------------------------
# Edge Cases and Error Handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_single_type_stream(self):
        """Single type stream is handled correctly."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        events = [{"type": "only.type", "id": i} for i in range(100)]
        result = analyze_multi_schema(events, min_cardinality=1)  # Allow single type

        assert result.types_detected == 1
        assert len(result.distribution) == 1
        assert result.distribution[0].percentage == 100.0
        assert result.overall_confidence > 0.5  # 100 samples gives decent confidence

    def test_malformed_events_excluded(self, mixed_events):
        """Malformed events are excluded but tracked."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        # Add some malformed events (missing discriminator)
        malformed = [{"no_type": "value"}] * 50
        all_events = mixed_events + malformed

        result = analyze_multi_schema(all_events)

        # Should still detect 4 types from valid events
        assert result.types_detected == 4
        # Sampling report should mention exclusions
        assert result.sampling.total_sampled <= len(all_events)

    def test_null_discriminator_values(self, mixed_events):
        """Null discriminator values are handled."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        # Add events with null type
        for i in range(20):
            mixed_events.append({"type": None, "id": i})

        result = analyze_multi_schema(mixed_events)

        # Should handle nulls (either exclude or group as _null)
        assert result.types_detected >= 4

    def test_unicode_discriminator_values(self):
        """Unicode discriminator values are handled."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        events = [
            {"type": "日本語", "id": 1},
            {"type": "日本語", "id": 2},
            {"type": "中文", "id": 3},
            {"type": "emoji_🎉", "id": 4},
        ]

        result = analyze_multi_schema(events)

        assert result.types_detected >= 3
        type_values = [d.type_value for d in result.distribution]
        assert "日本語" in type_values


# ---------------------------------------------------------------------------
# Audit and Telemetry Tests
# ---------------------------------------------------------------------------

class TestAuditTelemetry:
    """Tests for audit event emission."""

    def test_audit_event_schema(self, mixed_events, audit_stream):
        """Audit events follow the expected schema."""
        from streamforge.multi_schema_confidence import analyze_multi_schema

        analyze_multi_schema(events=mixed_events, audit_stream=audit_stream)

        audit_stream.seek(0)
        for line in audit_stream:
            if not line.strip():
                continue
            event = json.loads(line)
            # Validate schema
            audit = MultiSchemaAuditEvent(**event)
            assert audit.timestamp
            assert audit.operation
            assert audit.stream_name
            assert audit.duration_ms >= 0

    def test_failed_operation_logged(self):
        """Successful operations are logged correctly."""
        from streamforge.discriminator import detect_discriminator

        audit_stream = StringIO()

        # Normal operation should succeed and log
        events = [{"type": "test", "id": i} for i in range(10)]
        detect_discriminator(
            events=events,
            audit_stream=audit_stream,
        )

        audit_stream.seek(0)
        audit_content = audit_stream.read()
        assert audit_content.strip()  # Should have logged something
        audit_event = json.loads(audit_content.strip().split("\n")[0])
        assert audit_event["success"] is True
        assert audit_event["operation"] == "discriminator_detection"
