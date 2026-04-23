"""Tests for self-healing features: stale eviction, remediation hints, pre-drift trending."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


class TestRegistryStaleEviction:
    """Registry must self-clean stale entries."""

    def test_evict_stale_removes_old_entries(self):
        from streamforge.field_registry import FieldTypeRegistry, FieldTypeObservation
        reg = FieldTypeRegistry()
        old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        fresh_date = datetime.now(UTC).isoformat()
        reg._observations["old_field"] = FieldTypeObservation(
            field_path="old_field", field_type="string", confidence=0.9,
            last_seen=old_date, stream_names=["dead_stream"],
            observation_count=5, sample_values=[], pii_categories=[],
        )
        reg._observations["fresh_field"] = FieldTypeObservation(
            field_path="fresh_field", field_type="integer", confidence=0.95,
            last_seen=fresh_date, stream_names=["live_stream"],
            observation_count=10, sample_values=[], pii_categories=[],
        )
        evicted = reg.evict_stale(max_age_days=90)
        assert evicted == 1
        assert "old_field" not in reg._observations
        assert "fresh_field" in reg._observations

    def test_evict_stale_returns_zero_when_nothing_stale(self):
        from streamforge.field_registry import FieldTypeRegistry, FieldTypeObservation
        reg = FieldTypeRegistry()
        reg._observations["recent"] = FieldTypeObservation(
            field_path="recent", field_type="string", confidence=0.9,
            last_seen=datetime.now(UTC).isoformat(), stream_names=["s"],
            observation_count=1, sample_values=[], pii_categories=[],
        )
        assert reg.evict_stale(max_age_days=90) == 0

    def test_evict_disabled_with_zero_days(self):
        from streamforge.field_registry import FieldTypeRegistry
        reg = FieldTypeRegistry()
        assert reg.evict_stale(max_age_days=0) == 0


class TestRemediationHints:
    """Drift events must include actionable remediation guidance."""

    def test_field_removed_hint(self):
        from streamforge.detector.classify import remediation_hint
        from streamforge.models import DriftTier, FieldDrift
        drift = FieldDrift(
            field_path="amount", drift_type="field_removed",
            affected_event_rate=1.0, tier=DriftTier.TIER_3,
            auto_correctable=False,
            previous_presence_rate=1.0, observed_presence_rate=0.0,
        )
        hint = remediation_hint(drift)
        assert "amount" in hint
        assert "streamforge accept" in hint
        assert "rollback" in hint.lower() or "producer" in hint.lower()

    def test_type_changed_hint(self):
        from streamforge.detector.classify import remediation_hint
        from streamforge.models import DriftTier, FieldDrift, FieldType
        drift = FieldDrift(
            field_path="timestamp", drift_type="type_changed",
            affected_event_rate=1.0, tier=DriftTier.TIER_3,
            auto_correctable=False,
            previous_type=FieldType.INTEGER, observed_type=FieldType.FLOAT,
        )
        hint = remediation_hint(drift)
        assert "timestamp" in hint
        assert "integer" in hint.lower() or "float" in hint.lower()

    def test_new_pii_hint_urgent(self):
        from streamforge.detector.classify import remediation_hint
        from streamforge.models import DriftTier, FieldDrift
        drift = FieldDrift(
            field_path="user_ssn", drift_type="new_pii",
            affected_event_rate=0.5, tier=DriftTier.TIER_3,
            auto_correctable=False,
        )
        hint = remediation_hint(drift)
        assert "IMMEDIATE" in hint or "compliance" in hint.lower()

    def test_field_added_optional_no_action(self):
        from streamforge.detector.classify import remediation_hint
        from streamforge.models import DriftTier, FieldDrift
        drift = FieldDrift(
            field_path="metadata.tags", drift_type="field_added",
            affected_event_rate=0.1, tier=DriftTier.TIER_1,
            auto_correctable=True,
            observed_presence_rate=0.1,
        )
        hint = remediation_hint(drift)
        assert "no action" in hint.lower() or "auto" in hint.lower()

    def test_presence_drop_hint(self):
        from streamforge.detector.classify import remediation_hint
        from streamforge.models import DriftTier, FieldDrift
        drift = FieldDrift(
            field_path="user_id", drift_type="presence_drop",
            affected_event_rate=0.8, tier=DriftTier.TIER_2,
            auto_correctable=False,
            previous_presence_rate=0.95, observed_presence_rate=0.60,
        )
        hint = remediation_hint(drift)
        assert "user_id" in hint
        assert "95%" in hint or "60%" in hint


class TestPreDriftTrending:
    """Trend tracker must warn before drift thresholds are crossed."""

    def test_declining_trend_warns(self):
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=10, warn_cycles=3)
        # Simulate declining presence: 0.95, 0.90, 0.85, 0.80, 0.75
        for rate in [0.95, 0.90, 0.85, 0.80, 0.75]:
            tracker.record("amount", rate)
        warnings = tracker.check_trends(
            baseline_rates={"amount": 0.95},
            threshold=0.15,  # drift at 0.95 - 0.15 = 0.80
        )
        # amount is at 0.75, already below 0.80 — no warning (drift already happened)
        # Let's test with a field still above threshold
        tracker2 = PresenceTrendTracker(history_size=10, warn_cycles=5)
        for rate in [0.95, 0.93, 0.90, 0.87, 0.84]:
            tracker2.record("user_id", rate)
        warnings2 = tracker2.check_trends(
            baseline_rates={"user_id": 0.95},
            threshold=0.15,
        )
        # user_id at 0.84, drift line at 0.80, declining ~0.03/cycle -> crosses in ~1.3 cycles
        assert len(warnings2) >= 1
        assert warnings2[0]["field_path"] == "user_id"
        assert warnings2[0]["trend"] == "declining"

    def test_stable_field_no_warning(self):
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker()
        for rate in [0.95, 0.95, 0.96, 0.95, 0.94]:
            tracker.record("stable_field", rate)
        warnings = tracker.check_trends(baseline_rates={"stable_field": 0.95})
        assert len(warnings) == 0

    def test_too_few_data_points_no_warning(self):
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker()
        tracker.record("new_field", 0.90)
        tracker.record("new_field", 0.85)
        warnings = tracker.check_trends(baseline_rates={"new_field": 0.95})
        assert len(warnings) == 0  # need at least 3 points

    def test_save_and_load_roundtrip(self, tmp_path):
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker()
        tracker.record("f1", 0.95)
        tracker.record("f1", 0.90)
        tracker.record("f1", 0.85)
        path = tmp_path / "trends.json"
        tracker.save(path)
        loaded = PresenceTrendTracker.load(path)
        assert loaded._history["f1"] == [0.95, 0.90, 0.85]

    def test_history_bounded(self):
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=5)
        for i in range(20):
            tracker.record("field", 0.95 - i * 0.01)
        assert len(tracker._history["field"]) == 5
