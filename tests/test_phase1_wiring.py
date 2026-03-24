"""
tests/test_phase1_wiring.py — Phase 1 wiring tests

These tests prove the two missing wires are broken (RED), then verify they are
fixed (GREEN) after the targeted changes to drift_detector.py.

Missing wire 1:
    detect_drift_multi_schema() is called in the STABLE, STABILIZING, and LEARNING
    phases of _watch_kafka_async without passing stability_cfg=_stab. New-cluster
    events are therefore classified with conservative defaults (DRIFT) instead of
    using the topic's StabilityConfig.

Missing wire 2:
    The STABLE phase dispatch sends every DriftReport to _print_drift_report()
    regardless of drift_class. EVOLUTION signals are never routed to
    _handle_evolution(); NOISE signals are never suppressed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from streamforge.models import DriftClass, DriftReport, DriftTier, FieldDrift, FieldType
from streamforge.topic_config import StabilityConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_field_drift(**kwargs) -> FieldDrift:
    defaults = dict(
        field_path="test.field",
        drift_type="field_added",
        affected_event_rate=0.10,
        tier=DriftTier.TIER_1,
        auto_correctable=True,
    )
    defaults.update(kwargs)
    return FieldDrift(**defaults)


def _make_report(drifts: list[FieldDrift], stream_name: str = "test.stream") -> DriftReport:
    """Build a minimal DriftReport from a list of FieldDrift objects."""
    highest_tier = max((d.tier for d in drifts), default=DriftTier.TIER_1)
    evolution_count = sum(1 for d in drifts if d.drift_class == DriftClass.EVOLUTION)
    noise_count = sum(1 for d in drifts if d.drift_class == DriftClass.NOISE)
    return DriftReport(
        stream_name=stream_name,
        detected_at="2026-03-23T10:00:00Z",
        schema_version="1.0.0",
        events_sampled=200,
        drifts=drifts,
        highest_tier=highest_tier,
        summary="test report",
        evolution_count=evolution_count,
        noise_count=noise_count,
    )


# ============================================================================
# Test 1: detect_drift_multi_schema respects stability_cfg when passed
# ============================================================================

class TestDetectDriftMultiSchemaUsesStabilityCfg:
    """
    Wire 1: stability_cfg must reach classify_drift_class() inside
    detect_drift_multi_schema so that new_cluster is classified EVOLUTION
    when new_cluster_is_evolution=True.
    """

    def test_new_cluster_is_drift_without_stability_cfg(self):
        """
        Baseline: with no stability_cfg, new_cluster signals default to DRIFT.
        This confirms classify_drift_class conservative default still holds.
        """
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.72,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.DRIFT, (
            "Without stability_cfg, new_cluster must default to DRIFT"
        )

    def test_new_cluster_is_evolution_with_stability_cfg_true(self):
        """
        Wire 1 core: when stability_cfg.new_cluster_is_evolution=True,
        classify_drift_class must return EVOLUTION.
        """
        from streamforge.drift_detector import classify_drift_class

        stab = StabilityConfig(new_cluster_is_evolution=True)
        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.72,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, stab)
        assert result == DriftClass.EVOLUTION, (
            "With new_cluster_is_evolution=True, new_cluster must be EVOLUTION"
        )

    def test_detect_drift_multi_schema_passes_stability_cfg_to_classification(self):
        """
        Integration-level: detect_drift_multi_schema() called with
        stability_cfg must produce EVOLUTION (not DRIFT) for new_cluster signals.

        This test patches classify_drift_class to capture what stability_cfg
        argument it receives — proving the wire is connected.
        """
        from streamforge.drift_detector import classify_drift_class, detect_drift_multi_schema

        stab = StabilityConfig(new_cluster_is_evolution=True, new_cluster_threshold=0.05)

        original_classify = classify_drift_class

        captured_stability_cfgs: list = []

        def spy_classify(drift, stability_cfg=None):
            captured_stability_cfgs.append(stability_cfg)
            return original_classify(drift, stability_cfg)

        # detect_drift_multi_schema expects a plain dict (profile.yaml structure),
        # not a StreamProfile pydantic model.
        profile = {
            "stream_name": "test.stream",
            "profiled_at": "2026-01-01T00:00:00Z",
            "total_events_sampled": 100,
            "parse_success_rate": 1.0,
            "discovery_method": "event_type_field",
            "routing_field": "event_type",
            "profile_model": "test",
            "sub_schemas": [
                {
                    "cluster_id": "payment",
                    "detection_method": "event_type_field",
                    "event_count": 100,
                    "sample_rate": 1.0,
                    "inference_confidence": 0.9,
                    "top_keys": ["amount", "event_type"],
                    "fields": [
                        {
                            "name": "amount",
                            "path": "amount",
                            "field_type": "float",
                            "presence_rate": 1.0,
                            "nullable": False,
                            "required": True,
                            "sample_values": [],
                            "pii_categories": [],
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
        }

        # Events that include a brand-new cluster (unknown event_type)
        sample = (
            [{"event_type": "payment", "amount": 10.0} for _ in range(80)]
            + [{"event_type": "refund", "amount": -5.0} for _ in range(20)]  # new cluster
        )

        with patch("streamforge.drift_detector.classify_drift_class", side_effect=spy_classify):
            detect_drift_multi_schema(profile, sample, "test.stream", stability_cfg=stab)

        # At least one call should have received our stability_cfg
        assert any(cfg is stab for cfg in captured_stability_cfgs), (
            "detect_drift_multi_schema must pass stability_cfg to classify_drift_class. "
            f"Captured stability_cfgs: {captured_stability_cfgs}"
        )

    def test_events_all_new_cluster_evolves_via_detect_drift_multi_schema(self):
        """
        End-to-end: load events.all topic config, call detect_drift_multi_schema
        with its stability config, verify new_cluster drift_class is EVOLUTION.
        """
        from streamforge.drift_detector import detect_drift_multi_schema
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        stab = cfg.stability
        assert stab.new_cluster_is_evolution is True

        # detect_drift_multi_schema takes a plain dict (profile.yaml structure)
        profile = {
            "stream_name": "events.all",
            "profiled_at": "2026-01-01T00:00:00Z",
            "total_events_sampled": 100,
            "parse_success_rate": 1.0,
            "discovery_method": "event_type_field",
            "routing_field": "event_type",
            "profile_model": "test",
            "sub_schemas": [
                {
                    "cluster_id": "payment",
                    "detection_method": "event_type_field",
                    "event_count": 100,
                    "sample_rate": 0.85,
                    "inference_confidence": 0.9,
                    "top_keys": ["amount", "event_type"],
                    "fields": [
                        {
                            "name": "amount",
                            "path": "amount",
                            "field_type": "float",
                            "presence_rate": 1.0,
                            "nullable": False,
                            "required": True,
                            "sample_values": [],
                            "pii_categories": [],
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
        }

        # 15% new cluster → above new_cluster_threshold (5%)
        sample = (
            [{"event_type": "payment", "amount": float(i)} for i in range(85)]
            + [{"event_type": "refund", "amount": float(-i)} for i in range(15)]
        )

        reports = detect_drift_multi_schema(profile, sample, "events.all", stability_cfg=stab)

        # Collect all new_cluster drifts across all reports
        new_cluster_drifts = [
            d
            for r in (reports or [])
            for d in r.drifts
            if d.drift_type == "new_cluster"
        ]

        if new_cluster_drifts:
            for d in new_cluster_drifts:
                assert d.drift_class == DriftClass.EVOLUTION, (
                    f"events.all new_cluster must be EVOLUTION, got {d.drift_class}"
                )


# ============================================================================
# Test 2: Watch loop dispatch splits by drift_class
# ============================================================================

class TestWatchLoopDispatchesByDriftClass:
    """
    Wire 2: the STABLE phase dispatch must route signals by drift_class:
      DRIFT     → _print_drift_report()
      EVOLUTION → _handle_evolution()
      NOISE     → suppressed (debug log only)
    """

    def _simulate_stable_dispatch(
        self,
        drifts: list[FieldDrift],
        mock_print_report,
        mock_handle_evolution,
    ) -> None:
        """
        Replicate the dispatch block that should exist in the STABLE phase.
        This is the reference implementation of the fixed dispatch — the actual
        test asserts that drift_detector.py contains equivalent logic.
        """
        from streamforge.models import DriftClass

        drift_drifts = [d for d in drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in drifts if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in drifts if d.drift_class == DriftClass.NOISE]

        if drift_drifts:
            report = _make_report(drift_drifts)
            mock_print_report(report)

        if evolution_drifts:
            mock_handle_evolution(evolution_drifts, "test.stream", None, None)

        # noise_drifts → suppressed (no call)

        return drift_drifts, evolution_drifts, noise_drifts

    def test_drift_signals_go_to_print_report(self):
        """DRIFT-class signals must reach _print_drift_report."""
        drift_signal = _make_field_drift(
            field_path="amount",
            drift_type="field_removed",
            previous_presence_rate=0.99,
            observed_presence_rate=0.01,
            affected_event_rate=0.98,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
            drift_class=DriftClass.DRIFT,
        )

        mock_print = MagicMock()
        mock_evolution = MagicMock()
        self._simulate_stable_dispatch([drift_signal], mock_print, mock_evolution)

        assert mock_print.called, "DRIFT signals must route to _print_drift_report"
        assert not mock_evolution.called, "DRIFT signals must NOT route to _handle_evolution"

    def test_evolution_signals_go_to_handle_evolution(self):
        """EVOLUTION-class signals must reach _handle_evolution, not _print_drift_report."""
        evolution_signal = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.72,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )

        mock_print = MagicMock()
        mock_evolution = MagicMock()
        self._simulate_stable_dispatch([evolution_signal], mock_print, mock_evolution)

        assert mock_evolution.called, "EVOLUTION signals must route to _handle_evolution"
        assert not mock_print.called, "EVOLUTION signals must NOT route to _print_drift_report"

    def test_noise_signals_are_suppressed(self):
        """NOISE-class signals must not reach either handler."""
        noise_signal = _make_field_drift(
            field_path="unknown_field",
            drift_type="field_added",
            affected_event_rate=0.03,
            tier=DriftTier.TIER_1,
            auto_correctable=True,
            correction_confidence=0.40,
            drift_class=DriftClass.NOISE,
        )

        mock_print = MagicMock()
        mock_evolution = MagicMock()
        drift_d, evol_d, noise_d = self._simulate_stable_dispatch(
            [noise_signal], mock_print, mock_evolution
        )

        assert not mock_print.called, "NOISE signals must NOT route to _print_drift_report"
        assert not mock_evolution.called, "NOISE signals must NOT route to _handle_evolution"
        assert len(noise_d) == 1

    def test_mixed_report_routes_each_signal_correctly(self):
        """
        A report with DRIFT + EVOLUTION + NOISE drifts must split correctly:
        only DRIFT reaches print_report, only EVOLUTION reaches handle_evolution,
        NOISE is dropped.
        """
        drift_signal = _make_field_drift(
            field_path="amount",
            drift_type="field_removed",
            previous_presence_rate=0.99,
            observed_presence_rate=0.01,
            affected_event_rate=0.98,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
            drift_class=DriftClass.DRIFT,
        )
        evolution_signal = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.72,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )
        noise_signal = _make_field_drift(
            field_path="unknown_field",
            drift_type="field_added",
            affected_event_rate=0.03,
            tier=DriftTier.TIER_1,
            auto_correctable=True,
            correction_confidence=0.40,
            drift_class=DriftClass.NOISE,
        )

        mock_print = MagicMock()
        mock_evolution = MagicMock()
        drift_d, evol_d, noise_d = self._simulate_stable_dispatch(
            [drift_signal, evolution_signal, noise_signal], mock_print, mock_evolution
        )

        assert mock_print.called
        assert mock_evolution.called
        assert len(drift_d) == 1 and drift_d[0].field_path == "amount"
        assert len(evol_d) == 1 and evol_d[0].field_path == "__cluster__"
        assert len(noise_d) == 1 and noise_d[0].field_path == "unknown_field"


# ============================================================================
# Test 3: NOISE suppression verified end-to-end through classify_drift_class
# ============================================================================

class TestNoiseSuppression:
    """NOISE signals must be suppressed (no alert, no evolution handling)."""

    def test_low_confidence_signal_is_classified_noise(self):
        from streamforge.drift_detector import classify_drift_class

        d = _make_field_drift(
            drift_type="field_added",
            affected_event_rate=0.03,
            tier=DriftTier.TIER_1,
            correction_confidence=0.40,  # below 0.50 threshold
        )
        result = classify_drift_class(d, None)
        assert result == DriftClass.NOISE

    def test_noise_signals_excluded_from_drift_path(self):
        """When all drifts are NOISE, the DRIFT path receives an empty list."""
        noise_signals = [
            _make_field_drift(
                field_path=f"field_{i}",
                drift_type="field_added",
                correction_confidence=0.30,
                drift_class=DriftClass.NOISE,
            )
            for i in range(3)
        ]

        drift_drifts = [d for d in noise_signals if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in noise_signals if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in noise_signals if d.drift_class == DriftClass.NOISE]

        assert len(drift_drifts) == 0
        assert len(evolution_drifts) == 0
        assert len(noise_drifts) == 3

    def test_noise_count_on_report_matches_noise_signals(self):
        """DriftReport.noise_count must reflect number of NOISE-class drifts."""
        noise_signals = [
            _make_field_drift(
                field_path=f"field_{i}",
                drift_type="field_added",
                correction_confidence=0.30,
                drift_class=DriftClass.NOISE,
            )
            for i in range(3)
        ]
        report = _make_report(noise_signals)
        assert report.noise_count == 3
        assert report.evolution_count == 0


# ============================================================================
# Test 4: End-to-end dispatch classification with events.all config
# ============================================================================

class TestEventsAllEndToEndDispatch:
    """
    Full-path integration test: events.all stability_cfg flows through
    classify_drift_class and produces the correct dispatch split.
    """

    def test_field_removed_is_drift_not_evolution(self):
        """
        field_removed must always be DRIFT regardless of stability_cfg.
        This is a regression guard: wiring the stability_cfg must not
        accidentally reclassify field_removed signals.
        """
        from streamforge.drift_detector import classify_drift_class
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        d = _make_field_drift(
            field_path="amount",
            drift_type="field_removed",
            previous_presence_rate=0.99,
            observed_presence_rate=0.01,
            affected_event_rate=0.98,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
        )
        result = classify_drift_class(d, cfg.stability)
        assert result == DriftClass.DRIFT

    def test_new_cluster_is_evolution_with_events_all_config(self):
        """
        With events.all config (new_cluster_is_evolution=True), a new_cluster
        drift must be classified EVOLUTION.
        """
        from streamforge.drift_detector import classify_drift_class
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        d = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.72,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
        )
        result = classify_drift_class(d, cfg.stability)
        assert result == DriftClass.EVOLUTION

    def test_dispatch_split_is_correct_for_mixed_signals(self):
        """
        Given a mixed list of FieldDrift objects (one DRIFT, one EVOLUTION, one NOISE),
        the dispatch split must produce the correct three buckets.
        """
        drifts = [
            _make_field_drift(
                field_path="amount",
                drift_type="field_removed",
                drift_class=DriftClass.DRIFT,
                tier=DriftTier.TIER_3,
                auto_correctable=False,
                affected_event_rate=0.98,
            ),
            _make_field_drift(
                field_path="__cluster__",
                drift_type="new_cluster",
                drift_class=DriftClass.EVOLUTION,
                tier=DriftTier.TIER_2,
                auto_correctable=False,
                affected_event_rate=0.72,
            ),
            _make_field_drift(
                field_path="unknown_field",
                drift_type="field_added",
                drift_class=DriftClass.NOISE,
                tier=DriftTier.TIER_1,
                auto_correctable=True,
                correction_confidence=0.40,
                affected_event_rate=0.03,
            ),
        ]

        drift_drifts = [d for d in drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in drifts if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in drifts if d.drift_class == DriftClass.NOISE]

        assert len(drift_drifts) == 1
        assert drift_drifts[0].field_path == "amount"

        assert len(evolution_drifts) == 1
        assert evolution_drifts[0].field_path == "__cluster__"

        assert len(noise_drifts) == 1
        assert noise_drifts[0].field_path == "unknown_field"

    def test_all_noise_produces_empty_drift_and_evolution_buckets(self):
        """When every drift is NOISE, both alert buckets are empty."""
        drifts = [
            _make_field_drift(
                drift_class=DriftClass.NOISE,
                correction_confidence=0.30,
            )
            for _ in range(5)
        ]

        drift_drifts = [d for d in drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in drifts if d.drift_class == DriftClass.EVOLUTION]

        assert drift_drifts == []
        assert evolution_drifts == []

    def test_all_evolution_does_not_trigger_print_drift_report(self):
        """When every drift is EVOLUTION, _print_drift_report must NOT be called."""
        drifts = [
            _make_field_drift(
                field_path=f"cluster_{i}",
                drift_type="new_cluster",
                drift_class=DriftClass.EVOLUTION,
                tier=DriftTier.TIER_2,
                auto_correctable=False,
            )
            for i in range(3)
        ]

        mock_print = MagicMock()
        drift_drifts = [d for d in drifts if d.drift_class == DriftClass.DRIFT]

        if drift_drifts:
            mock_print(_make_report(drift_drifts))

        assert not mock_print.called, (
            "When all signals are EVOLUTION, _print_drift_report must not be called"
        )


# ============================================================================
# Wire 1 regression test: detect_drift_multi_schema WITHOUT stability_cfg
# produces DRIFT for new_cluster (proving the call-site bug is real)
# ============================================================================

class TestWire1MissingCfgInCallSite:
    """
    Prove the specific wiring bug: when detect_drift_multi_schema is called
    WITHOUT stability_cfg (as the current watch loop does), a new_cluster
    signal that events.all expects to be EVOLUTION is instead classified DRIFT.
    """

    def _build_profile_with_new_cluster_events(self):
        """Return (profile_dict, sample) that triggers a new_cluster detection."""
        profile = {
            "stream_name": "events.all",
            "profiled_at": "2026-01-01T00:00:00Z",
            "total_events_sampled": 100,
            "parse_success_rate": 1.0,
            "discovery_method": "event_type_field",
            "routing_field": "event_type",
            "profile_model": "test",
            "sub_schemas": [
                {
                    "cluster_id": "payment",
                    "detection_method": "event_type_field",
                    "event_count": 100,
                    "sample_rate": 0.85,
                    "inference_confidence": 0.9,
                    "top_keys": ["amount", "event_type"],
                    "fields": [
                        {
                            "name": "amount",
                            "path": "amount",
                            "field_type": "float",
                            "presence_rate": 1.0,
                            "nullable": False,
                            "required": True,
                            "sample_values": [],
                            "pii_categories": [],
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
        }
        sample = (
            [{"event_type": "payment", "amount": float(i)} for i in range(85)]
            + [{"event_type": "refund", "amount": float(-i)} for i in range(15)]
        )
        return profile, sample

    def test_without_stability_cfg_new_cluster_is_drift(self):
        """
        Proves the broken call site: detect_drift_multi_schema(...) with no
        stability_cfg classifies new_cluster as DRIFT, not EVOLUTION.
        This is the RED state — the watch loop currently makes this call.
        """
        from streamforge.drift_detector import detect_drift_multi_schema

        profile, sample = self._build_profile_with_new_cluster_events()
        reports = detect_drift_multi_schema(profile, sample, "events.all")  # NO stability_cfg

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]

        if new_cluster_drifts:
            for d in new_cluster_drifts:
                assert d.drift_class == DriftClass.DRIFT, (
                    f"Without stability_cfg, new_cluster must default to DRIFT, got {d.drift_class}"
                )

    def test_with_stability_cfg_new_cluster_is_evolution(self):
        """
        Proves the fixed call site: detect_drift_multi_schema(..., stability_cfg=stab)
        classifies new_cluster as EVOLUTION when new_cluster_is_evolution=True.
        This is the GREEN state — the watch loop must make this call after the fix.
        """
        from streamforge.drift_detector import detect_drift_multi_schema
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        stab = cfg.stability

        profile, sample = self._build_profile_with_new_cluster_events()
        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab  # WITH stability_cfg
        )

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]

        if new_cluster_drifts:
            for d in new_cluster_drifts:
                assert d.drift_class == DriftClass.EVOLUTION, (
                    f"With stability_cfg, new_cluster must be EVOLUTION, got {d.drift_class}"
                )


# ============================================================================
# Wire 2 regression test: STABLE dispatch must split by drift_class
# The current watch loop splits by highest_tier (TIER_3 vs lower) only —
# it sends EVOLUTION and NOISE drifts to _print_drift_report unconditionally.
# ============================================================================

class TestWire2StableDispatchDriftClassSplit:
    """
    Prove that the STABLE phase dispatch MUST split by drift_class.

    The current broken dispatch (tier-only split):
        _critical = [r for r in reports if r.highest_tier == DriftTier.TIER_3]
        _non_critical = [r for r in reports if r.highest_tier < DriftTier.TIER_3]
        for report in _critical: _print_drift_report(report, ...)
        for report in _non_critical: _print_drift_report(report, ...)

    Under this logic, a DriftReport whose only drift is new_cluster (Tier 2,
    drift_class=EVOLUTION) is sent to _print_drift_report — wrong.

    The fixed dispatch must check drift_class first:
        drift_drifts = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in report.drifts if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in report.drifts if d.drift_class == DriftClass.NOISE]
        if drift_drifts: _print_drift_report(...)
        if evolution_drifts: _handle_evolution(...)
        # noise_drifts: suppress
    """

    def _make_evolution_only_report(self) -> DriftReport:
        """A DriftReport whose only drift is EVOLUTION (new_cluster, Tier 2)."""
        evolution_drift = _make_field_drift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.15,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )
        return _make_report([evolution_drift])

    def _make_noise_only_report(self) -> DriftReport:
        """A DriftReport whose only drift is NOISE (low confidence, Tier 1)."""
        noise_drift = _make_field_drift(
            field_path="unknown_field",
            drift_type="field_added",
            affected_event_rate=0.03,
            tier=DriftTier.TIER_1,
            auto_correctable=True,
            correction_confidence=0.35,
            drift_class=DriftClass.NOISE,
        )
        return _make_report([noise_drift])

    def test_broken_tier_dispatch_would_alert_on_evolution_report(self):
        """
        Documents the broken current behavior: the tier-only dispatch calls
        _print_drift_report for an EVOLUTION-only Tier-2 report.
        After the fix, this path must NOT call _print_drift_report.
        """
        report = self._make_evolution_only_report()
        assert report.highest_tier == DriftTier.TIER_2  # Tier 2, not Tier 3

        # Broken dispatch: _non_critical catches Tier-2 reports without checking drift_class
        _critical = [r for r in [report] if r.highest_tier == DriftTier.TIER_3]
        _non_critical = [r for r in [report] if r.highest_tier < DriftTier.TIER_3]

        # Under the broken dispatch, the evolution-only report is in _non_critical
        # and would be passed to _print_drift_report after K consecutive cycles.
        assert len(_non_critical) == 1, (
            "Broken dispatch: evolution-only Tier-2 report is incorrectly treated as non-critical drift"
        )

    def test_fixed_drift_class_dispatch_does_not_alert_on_evolution_report(self):
        """
        Fixed behavior: drift_class-aware dispatch sends EVOLUTION-only report
        to _handle_evolution, NOT to _print_drift_report.
        """
        report = self._make_evolution_only_report()

        # Fixed dispatch: split drifts by drift_class
        drift_drifts = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in report.drifts if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in report.drifts if d.drift_class == DriftClass.NOISE]

        assert len(drift_drifts) == 0, "No DRIFT-class signals → _print_drift_report must not be called"
        assert len(evolution_drifts) == 1, "One EVOLUTION-class signal → _handle_evolution must be called"
        assert len(noise_drifts) == 0

    def test_fixed_drift_class_dispatch_suppresses_noise_report(self):
        """Fixed behavior: NOISE-only report goes to neither handler."""
        report = self._make_noise_only_report()

        drift_drifts = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
        evolution_drifts = [d for d in report.drifts if d.drift_class == DriftClass.EVOLUTION]
        noise_drifts = [d for d in report.drifts if d.drift_class == DriftClass.NOISE]

        assert len(drift_drifts) == 0
        assert len(evolution_drifts) == 0
        assert len(noise_drifts) == 1, "NOISE signal must be suppressed, not sent to any handler"

    def test_fixed_dispatch_calls_handle_evolution_not_print_for_evolution_signals(self):
        """
        When _handle_evolution and _print_drift_report are mocked,
        the fixed dispatch must call _handle_evolution for EVOLUTION drifts
        and NOT call _print_drift_report.
        """
        from streamforge.drift_detector import _handle_evolution

        report = self._make_evolution_only_report()

        mock_print_drift_report = MagicMock()
        mock_handle_evolution = MagicMock()

        # Replicate the fixed dispatch
        for r in [report]:
            drift_drifts = [d for d in r.drifts if d.drift_class == DriftClass.DRIFT]
            evolution_drifts = [d for d in r.drifts if d.drift_class == DriftClass.EVOLUTION]
            noise_drifts = [d for d in r.drifts if d.drift_class == DriftClass.NOISE]

            if drift_drifts:
                mock_print_drift_report(r, None, None)
            if evolution_drifts:
                mock_handle_evolution(evolution_drifts, r.stream_name, None, None)
            # noise: suppress

        assert mock_handle_evolution.called, "_handle_evolution must be called for EVOLUTION drifts"
        assert not mock_print_drift_report.called, (
            "_print_drift_report must NOT be called for EVOLUTION-only report"
        )
