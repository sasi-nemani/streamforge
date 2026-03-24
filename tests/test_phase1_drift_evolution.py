"""
tests/test_phase1_drift_evolution.py — Phase 1: DriftClass TDD tests

RED phase: these tests define the expected behaviour before implementation.
All tests here must pass GREEN after Phase 1 implementation is complete.

Scope:
  Part A: DriftClass enum + drift_class field on FieldDrift + DriftReport counts
  Part B: classify_drift_class() function logic
  Part C: detect_drift / detect_drift_multi_schema wire-up
  Part D: _handle_evolution() dispatch helper
  Part E: DLQRouter (minimal, opt-in, never raises)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from streamforge.models import DriftTier, FieldDrift, FieldType
from streamforge.topic_config import StabilityConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_field_drift(**kwargs) -> FieldDrift:
    """Return a FieldDrift with sane defaults — callers override what they need."""
    defaults = dict(
        field_path="test.field",
        drift_type="field_added",
        affected_event_rate=0.10,
        tier=DriftTier.TIER_1,
        auto_correctable=True,
    )
    defaults.update(kwargs)
    return FieldDrift(**defaults)


def _stability(new_cluster_is_evolution: bool) -> StabilityConfig:
    return StabilityConfig(new_cluster_is_evolution=new_cluster_is_evolution)


# ============================================================================
# Part A: DriftClass enum
# ============================================================================

class TestDriftClassEnum:
    """DriftClass must exist, be importable, and have correct members."""

    def test_drift_class_importable(self):
        from streamforge.models import DriftClass  # noqa: F401

    def test_drift_class_has_drift(self):
        from streamforge.models import DriftClass
        assert DriftClass.DRIFT == "drift"

    def test_drift_class_has_evolution(self):
        from streamforge.models import DriftClass
        assert DriftClass.EVOLUTION == "evolution"

    def test_drift_class_has_noise(self):
        from streamforge.models import DriftClass
        assert DriftClass.NOISE == "noise"

    def test_drift_class_is_str_enum(self):
        from enum import StrEnum
        from streamforge.models import DriftClass
        assert issubclass(DriftClass, StrEnum)


# ============================================================================
# Part A: drift_class field on FieldDrift
# ============================================================================

class TestFieldDriftHasDriftClass:
    """FieldDrift model must carry a drift_class field, defaulting to DRIFT."""

    def test_field_drift_has_drift_class_field(self):
        from streamforge.models import DriftClass
        d = _make_field_drift()
        assert hasattr(d, "drift_class")

    def test_field_drift_drift_class_defaults_to_drift(self):
        from streamforge.models import DriftClass
        d = _make_field_drift()
        assert d.drift_class == DriftClass.DRIFT

    def test_field_drift_drift_class_can_be_set_to_evolution(self):
        from streamforge.models import DriftClass
        d = _make_field_drift(drift_class=DriftClass.EVOLUTION)
        assert d.drift_class == DriftClass.EVOLUTION

    def test_field_drift_drift_class_can_be_set_to_noise(self):
        from streamforge.models import DriftClass
        d = _make_field_drift(drift_class=DriftClass.NOISE)
        assert d.drift_class == DriftClass.NOISE


# ============================================================================
# Part A: evolution_count and noise_count on DriftReport
# ============================================================================

class TestDriftReportCounts:
    """DriftReport must expose evolution_count and noise_count integer fields."""

    def test_drift_report_has_evolution_count(self):
        from streamforge.models import DriftClass, DriftReport
        report = DriftReport(
            stream_name="s",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="1.0.0",
            events_sampled=100,
            drifts=[],
            highest_tier=DriftTier.TIER_1,
            summary="test",
        )
        assert hasattr(report, "evolution_count")
        assert report.evolution_count == 0

    def test_drift_report_has_noise_count(self):
        from streamforge.models import DriftReport
        report = DriftReport(
            stream_name="s",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="1.0.0",
            events_sampled=100,
            drifts=[],
            highest_tier=DriftTier.TIER_1,
            summary="test",
        )
        assert hasattr(report, "noise_count")
        assert report.noise_count == 0

    def test_drift_report_evolution_count_is_int(self):
        from streamforge.models import DriftReport
        report = DriftReport(
            stream_name="s",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="1.0.0",
            events_sampled=100,
            drifts=[],
            highest_tier=DriftTier.TIER_1,
            summary="test",
        )
        assert isinstance(report.evolution_count, int)

    def test_drift_report_noise_count_can_be_set(self):
        from streamforge.models import DriftReport
        report = DriftReport(
            stream_name="s",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="1.0.0",
            events_sampled=100,
            drifts=[],
            highest_tier=DriftTier.TIER_1,
            summary="test",
            noise_count=3,
        )
        assert report.noise_count == 3


# ============================================================================
# Part B: classify_drift_class() — new_cluster
# ============================================================================

class TestClassifyDriftClassNewCluster:
    """new_cluster → EVOLUTION when new_cluster_is_evolution=True, else DRIFT."""

    def test_new_cluster_is_evolution_when_flag_true(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.35,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, _stability(new_cluster_is_evolution=True))
        assert result == DriftClass.EVOLUTION

    def test_new_cluster_is_drift_when_flag_false(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.35,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, _stability(new_cluster_is_evolution=False))
        assert result == DriftClass.DRIFT

    def test_new_cluster_defaults_to_drift_when_stability_cfg_none(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.35,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT


# ============================================================================
# Part B: classify_drift_class() — field_added
# ============================================================================

class TestClassifyDriftClassFieldAdded:
    """field_added: low presence → EVOLUTION, high presence → DRIFT."""

    def test_field_added_low_presence_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.30,  # < 0.5
            tier=DriftTier.TIER_1,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_field_added_high_presence_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.80,  # >= 0.5
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_field_added_exactly_half_presence_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.5,   # boundary: >= 0.5 → DRIFT
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_field_added_zero_presence_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.0,
            tier=DriftTier.TIER_1,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION


# ============================================================================
# Part B: classify_drift_class() — field_removed
# ============================================================================

class TestClassifyDriftClassFieldRemoved:
    """field_removed where field was required → always DRIFT."""

    def test_field_removed_required_field_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            field_path="amount",
            drift_type="field_removed",
            previous_presence_rate=0.98,
            observed_presence_rate=0.01,
            affected_event_rate=0.97,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_field_removed_optional_field_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_removed",
            previous_presence_rate=0.50,
            observed_presence_rate=0.01,
            affected_event_rate=0.49,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT


# ============================================================================
# Part B: classify_drift_class() — type_changed
# ============================================================================

class TestClassifyDriftClassTypeChanged:
    """Type widening → EVOLUTION. Type narrowing → DRIFT. Timestamp-to-timestamp → EVOLUTION."""

    def test_type_widening_int_to_float_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.INTEGER,
            observed_type=FieldType.FLOAT,
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_type_widening_int_to_mixed_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.INTEGER,
            observed_type=FieldType.MIXED,
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_type_widening_any_to_string_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        # string to mixed also is widening
        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.STRING,
            observed_type=FieldType.MIXED,
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_type_narrowing_string_to_int_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.STRING,
            observed_type=FieldType.INTEGER,
            tier=DriftTier.TIER_3,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_type_narrowing_mixed_to_string_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.MIXED,
            observed_type=FieldType.STRING,
            tier=DriftTier.TIER_3,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_type_narrowing_float_to_int_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.FLOAT,
            observed_type=FieldType.INTEGER,
            tier=DriftTier.TIER_3,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_timestamp_format_change_is_evolution(self):
        """Timestamp-to-timestamp format changes are semantically equivalent — EVOLUTION."""
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="type_changed",
            previous_type=FieldType.TIMESTAMP_EPOCH_MS,
            observed_type=FieldType.TIMESTAMP_ISO8601,
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION


# ============================================================================
# Part B: classify_drift_class() — enum_changed
# ============================================================================

class TestClassifyDriftClassEnumChanged:
    """enum_changed: new values only → EVOLUTION. Removed values → DRIFT."""

    def test_enum_expansion_only_new_values_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="enum_changed",
            previous_enum_values=["USD", "EUR"],
            observed_enum_values=["USD", "EUR", "GBP"],  # only additions
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_enum_shrinkage_values_removed_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="enum_changed",
            previous_enum_values=["USD", "EUR", "GBP"],
            observed_enum_values=["USD"],  # GBP and EUR removed
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT

    def test_enum_changed_no_removal_but_new_values_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="enum_changed",
            previous_enum_values=["COMPLETED", "FAILED", "PENDING"],
            observed_enum_values=["COMPLETED", "FAILED", "PENDING", "REFUNDED"],
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_enum_changed_with_removal_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        # Both added and removed
        d = _make_field_drift(
            drift_type="enum_changed",
            previous_enum_values=["A", "B", "C"],
            observed_enum_values=["A", "B", "D"],  # C removed, D added
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT


# ============================================================================
# Part B: classify_drift_class() — presence_rate_changed
# ============================================================================

class TestClassifyDriftClassPresenceRateChanged:
    """presence rate rising → EVOLUTION. Rate dropping → DRIFT."""

    def test_presence_increase_is_evolution(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="presence_increase",
            previous_presence_rate=0.50,
            observed_presence_rate=0.90,
            tier=DriftTier.TIER_1,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.EVOLUTION

    def test_presence_drop_is_drift(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="presence_drop",
            previous_presence_rate=0.90,
            observed_presence_rate=0.50,
            tier=DriftTier.TIER_2,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT


# ============================================================================
# Part B: classify_drift_class() — low confidence → NOISE
# ============================================================================

class TestClassifyDriftClassNoise:
    """Any drift with correction_confidence < 0.50 → NOISE. Uses a proxy field."""

    def test_low_confidence_field_is_noise(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        # Simulate a low-confidence signal by using correction_confidence as the proxy
        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.06,
            affected_event_rate=0.06,
            tier=DriftTier.TIER_1,
            correction_confidence=0.40,  # < 0.50
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.NOISE

    def test_high_confidence_field_not_noise(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.30,
            affected_event_rate=0.30,
            tier=DriftTier.TIER_1,
            correction_confidence=0.90,  # >= 0.50
        )
        result = classify_drift_class(d, None)
        # Should be EVOLUTION (low presence) not NOISE
        assert result == DriftClass.EVOLUTION

    def test_exactly_half_confidence_is_not_noise(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.30,
            affected_event_rate=0.30,
            tier=DriftTier.TIER_1,
            correction_confidence=0.50,  # exactly 0.50 → not noise
        )
        result = classify_drift_class(d, None)
        assert result != DriftClass.NOISE


# ============================================================================
# Part C: detect_drift() wires up drift_class
# ============================================================================

class TestDetectDriftWiresDriftClass:
    """detect_drift() must set drift_class on every FieldDrift it produces."""

    def _make_schema(self, fields):
        from streamforge.models import FieldSchema, InferredSchema
        return InferredSchema(
            stream_name="test.stream",
            inferred_at="2026-01-01T00:00:00Z",
            event_count_sampled=20,
            fields=fields,
            inference_model="test",
            inference_confidence=0.9,
        )

    def test_detect_drift_sets_drift_class_on_each_field_drift(self):
        from streamforge.models import DriftClass, FieldSchema, InferredSchema
        from streamforge.drift_detector import detect_drift

        schema = self._make_schema([
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
                required=True,
            )
        ])
        # Remove the required field → field_removed DRIFT
        new_sample = [{"event_id": f"id-{i}"} for i in range(30)]
        report = detect_drift(schema, new_sample, "test.stream")
        assert report is not None
        for d in report.drifts:
            assert hasattr(d, "drift_class")
            assert d.drift_class in list(DriftClass)

    def test_detect_drift_drift_class_is_not_none(self):
        from streamforge.models import DriftClass, FieldSchema
        from streamforge.drift_detector import detect_drift

        schema = self._make_schema([
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
                required=True,
            )
        ])
        new_sample = [{"event_id": f"id-{i}"} for i in range(30)]
        report = detect_drift(schema, new_sample, "test.stream")
        assert report is not None
        for d in report.drifts:
            assert d.drift_class is not None

    def test_detect_drift_field_removed_has_drift_class(self):
        from streamforge.models import DriftClass, FieldSchema
        from streamforge.drift_detector import detect_drift

        schema = self._make_schema([
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
                required=True,
            )
        ])
        new_sample = [{"event_id": f"id-{i}"} for i in range(30)]
        report = detect_drift(schema, new_sample, "test.stream")
        assert report is not None
        removed_drifts = [d for d in report.drifts if d.drift_type == "field_removed"]
        assert len(removed_drifts) >= 1
        assert removed_drifts[0].drift_class == DriftClass.DRIFT

    def test_detect_drift_new_optional_field_is_evolution(self):
        """A new field with low presence should be classified as EVOLUTION."""
        from streamforge.models import DriftClass, FieldSchema
        from streamforge.drift_detector import detect_drift

        schema = self._make_schema([
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
            )
        ])
        # 20% of events have a new optional field
        new_sample = [{"amount": float(i)} for i in range(30)]
        new_sample[:6] = [{"amount": float(i), "metadata": "extra"} for i in range(6)]
        report = detect_drift(schema, new_sample, "test.stream")
        if report is not None:
            added = [d for d in report.drifts if d.drift_type == "field_added"]
            if added:
                # presence_rate ≈ 6/30 = 0.2 → EVOLUTION
                assert added[0].drift_class == DriftClass.EVOLUTION


# ============================================================================
# Part C: DriftReport counts evolution_count and noise_count
# ============================================================================

class TestDriftReportCountsFilled:
    """detect_drift() must populate evolution_count and noise_count on DriftReport."""

    def test_detect_drift_report_has_evolution_count_filled(self):
        from streamforge.models import FieldSchema
        from streamforge.drift_detector import detect_drift

        schema_fields = [
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
            )
        ]
        from streamforge.models import InferredSchema
        schema = InferredSchema(
            stream_name="test.stream",
            inferred_at="2026-01-01T00:00:00Z",
            event_count_sampled=20,
            fields=schema_fields,
            inference_model="test",
            inference_confidence=0.9,
        )
        new_sample = [{"event_id": f"id-{i}"} for i in range(30)]
        report = detect_drift(schema, new_sample, "test.stream")
        assert report is not None
        assert isinstance(report.evolution_count, int)
        assert isinstance(report.noise_count, int)


# ============================================================================
# Part C: events.all config → new_cluster should be EVOLUTION
# ============================================================================

class TestEventsAllConfig:
    """Integration test: events.all topic config sets new_cluster_is_evolution=True."""

    def test_events_all_config_new_cluster_is_evolution_flag(self):
        """Load the real events.all config and confirm the stability flag."""
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.stability.new_cluster_is_evolution is True

    def test_events_all_new_cluster_classified_as_evolution(self):
        """With events.all config, a new_cluster drift should be EVOLUTION."""
        from streamforge.models import DriftClass
        from streamforge.drift_detector import classify_drift_class
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.35,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, cfg.stability)
        assert result == DriftClass.EVOLUTION


# ============================================================================
# Part D: _handle_evolution() — prints, doesn't raise, optional VCS
# ============================================================================

class TestHandleEvolution:
    """_handle_evolution must log at info level and never raise."""

    def test_handle_evolution_is_importable(self):
        from streamforge.drift_detector import _handle_evolution  # noqa: F401

    def test_handle_evolution_does_not_raise(self):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import _handle_evolution

        signals = [
            _make_field_drift(
                drift_type="field_added",
                observed_presence_rate=0.20,
                drift_class=DriftClass.EVOLUTION,
            )
        ]
        # Must not raise even with None topic_cfg and no schema_dir
        _handle_evolution(signals, "test.stream", None, None)

    def test_handle_evolution_prints_evolution_message(self, capsys):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import _handle_evolution

        signals = [
            _make_field_drift(
                field_path="new.field",
                drift_type="field_added",
                observed_presence_rate=0.20,
                drift_class=DriftClass.EVOLUTION,
            )
        ]
        _handle_evolution(signals, "my.stream", None, None)
        captured = capsys.readouterr()
        assert "EVOLUTION" in captured.out
        assert "my.stream" in captured.out

    def test_handle_evolution_prints_count(self, capsys):
        from streamforge.models import DriftClass
        from streamforge.drift_detector import _handle_evolution

        signals = [
            _make_field_drift(
                field_path=f"field.{i}",
                drift_type="field_added",
                observed_presence_rate=0.20,
                drift_class=DriftClass.EVOLUTION,
            )
            for i in range(3)
        ]
        _handle_evolution(signals, "my.stream", None, None)
        captured = capsys.readouterr()
        assert "3" in captured.out

    def test_handle_evolution_with_broken_vcs_does_not_raise(self):
        """Even when VCS is configured but fails, _handle_evolution must not raise."""
        from streamforge.models import DriftClass
        from streamforge.drift_detector import _handle_evolution
        from streamforge.topic_config import TopicConfig

        # Create a topic_cfg with vcs_enabled=True but no real backend
        cfg = TopicConfig(topic="test", env="dev", vcs_enabled=True)
        signals = [
            _make_field_drift(
                drift_type="field_added",
                observed_presence_rate=0.20,
                drift_class=DriftClass.EVOLUTION,
            )
        ]
        # Should never raise regardless of VCS failure
        _handle_evolution(signals, "test.stream", None, cfg)

    def test_handle_evolution_empty_signals_does_not_raise(self):
        """Empty signal list is valid — should produce no output and not raise."""
        from streamforge.drift_detector import _handle_evolution
        _handle_evolution([], "test.stream", None, None)


# ============================================================================
# Part E: DLQRouter — never raises, returns 0 when disabled
# ============================================================================

class TestDLQConfig:
    """DLQConfig must be importable as a dataclass with expected defaults."""

    def test_dlq_config_importable(self):
        from streamforge.dlq import DLQConfig  # noqa: F401

    def test_dlq_config_defaults(self):
        from streamforge.dlq import DLQConfig
        cfg = DLQConfig()
        assert cfg.enabled is False
        assert cfg.topic_suffix == ".dlq"
        assert cfg.include_payload is True
        assert cfg.min_tier == 3

    def test_dlq_config_is_dataclass(self):
        import dataclasses
        from streamforge.dlq import DLQConfig
        assert dataclasses.is_dataclass(DLQConfig)


class TestDLQRouter:
    """DLQRouter must never raise and return 0 when disabled."""

    def test_dlq_router_importable(self):
        from streamforge.dlq import DLQRouter  # noqa: F401

    def test_route_returns_zero_when_disabled(self):
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.all", ["localhost:9092"], DLQConfig(enabled=False))
        result = router.route([{"test": 1}], "field_removed")
        assert result == 0

    def test_route_does_not_raise_on_empty_events_when_disabled(self):
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.all", ["localhost:9092"], DLQConfig(enabled=False))
        result = router.route([], "field_removed")
        assert result == 0

    def test_route_swallows_exception_when_enabled_but_kafka_missing(self):
        """
        When DLQ is enabled but kafka-python is not installed (or broker unreachable),
        route() must return 0 and never raise.
        """
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.all", ["badhost:9999"], DLQConfig(enabled=True))
        # Simulate ImportError for kafka-python by patching the import
        with patch("builtins.__import__", side_effect=ImportError("kafka not installed")):
            result = router.route([{"event": "data"}], "field_removed")
        assert result == 0

    def test_route_returns_int(self):
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.all", ["localhost:9092"], DLQConfig(enabled=False))
        result = router.route([{"test": 1}], "field_removed")
        assert isinstance(result, int)

    def test_dlq_router_topic_suffix(self):
        """DLQ topic name = source topic + suffix."""
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.payments", ["localhost:9092"], DLQConfig(enabled=False))
        assert router.dlq_topic == "events.payments.dlq"

    def test_dlq_router_custom_suffix(self):
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.payments", ["localhost:9092"], DLQConfig(enabled=False, topic_suffix=".dead"))
        assert router.dlq_topic == "events.payments.dead"

    def test_route_with_exception_in_publish_returns_zero(self):
        """
        route() must swallow internal exceptions and return 0 (non-fatal).
        """
        from streamforge.dlq import DLQConfig, DLQRouter

        router = DLQRouter("events.all", ["localhost:9092"], DLQConfig(enabled=True))
        # Patch _publish to raise RuntimeError
        with patch.object(router, "_publish", side_effect=RuntimeError("boom")):
            result = router.route([{"event": "data"}], "field_removed")
        assert result == 0


# ============================================================================
# Regression: existing tests still work — drift path unchanged
# ============================================================================

class TestExistingDriftPathUnchanged:
    """Existing DRIFT-class signals must still produce reports via the alert path."""

    def _make_schema(self, fields):
        from streamforge.models import FieldSchema, InferredSchema
        return InferredSchema(
            stream_name="test.stream",
            inferred_at="2026-01-01T00:00:00Z",
            event_count_sampled=20,
            fields=fields,
            inference_model="test",
            inference_confidence=0.9,
        )

    def test_field_removed_still_produces_drift_report(self):
        from streamforge.models import DriftClass, FieldSchema
        from streamforge.drift_detector import detect_drift

        schema = self._make_schema([
            FieldSchema(
                name="amount",
                path="amount",
                field_type=FieldType.FLOAT,
                presence_rate=1.0,
                required=True,
            )
        ])
        new_sample = [{"event_id": f"id-{i}"} for i in range(30)]
        report = detect_drift(schema, new_sample, "test.stream")
        assert report is not None
        assert len(report.drifts) >= 1
        drift_class_drifts = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
        assert len(drift_class_drifts) >= 1

    def test_classify_drift_tier_unchanged_for_field_removed(self):
        """classify_drift_tier() must still work exactly as before."""
        from streamforge.drift_detector import classify_drift_tier

        d = _make_field_drift(
            drift_type="field_removed",
            previous_presence_rate=0.98,
            observed_presence_rate=0.01,
            affected_event_rate=0.97,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
        )
        tier = classify_drift_tier(d)
        assert tier == DriftTier.TIER_3

    def test_classify_drift_tier_unchanged_for_field_added_low_presence(self):
        from streamforge.drift_detector import classify_drift_tier

        d = _make_field_drift(
            drift_type="field_added",
            observed_presence_rate=0.20,
            tier=DriftTier.TIER_1,
        )
        tier = classify_drift_tier(d)
        assert tier == DriftTier.TIER_1
