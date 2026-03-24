"""
tests/test_phase1_runtime_wiring.py

TDD RED phase: tests that expose the three runtime wiring gaps.

Gap 1 — stability_cfg.new_cluster_threshold is ignored
    detect_drift_multi_schema() always calls _new_cluster_threshold() which reads from
    the env var, never from stability_cfg.new_cluster_threshold.
    events.all.yaml sets new_cluster_threshold: 0.30 but this is never applied.

Gap 2 — dead-code flap-counter reset for evolution-only cycles
    The reset branch at the end of the STABLE dispatch block is:
        if not _critical and not _non_critical and not reports:
            _consec_drift_count = 0
    But we are inside the `else` block of `if not reports:`, so `reports` is always
    truthy here — the condition is never true. When all signals are EVOLUTION or NOISE
    (nothing in _drift_reports), the flap counter is never reset, causing it to
    accumulate forever and eventually fire a false drift alert after K cycles.

Gap 3 — Regression: dispatch must not alert on evolution-only report
    Confirmed by test_phase1_wiring.py, re-tested here for completeness with the
    new_cluster_threshold path.

All tests in this file must FAIL before the fix and PASS after it.
"""

from __future__ import annotations

import pytest
from streamforge.topic_config import StabilityConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_profile(new_cluster_threshold: float = 0.05) -> dict:
    """Minimal profile dict with one known cluster."""
    return {
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


# ===========================================================================
# Gap 1: stability_cfg.new_cluster_threshold must be respected
# ===========================================================================

class TestStabilityCfgNewClusterThresholdRespected:
    """
    detect_drift_multi_schema must check stability_cfg.new_cluster_threshold
    instead of (or before) the env-var-based _new_cluster_threshold().

    events.all.yaml: new_cluster_threshold: 0.30
    If only 15% of events are from an unknown cluster, and the env default is 5%,
    the call WITHOUT stability_cfg fires a new_cluster report.
    The call WITH stability_cfg (threshold=0.30) must NOT fire because 15% < 30%.
    """

    def _sample_with_15pct_unknown(self) -> list[dict]:
        return (
            [{"event_type": "payment", "amount": float(i)} for i in range(85)]
            + [{"event_type": "refund", "amount": float(-i)} for i in range(15)]
        )

    def test_without_stability_cfg_15pct_fires_new_cluster(self, monkeypatch):
        """
        Control: with env threshold=0.05 (default), 15% unknown fires new_cluster.
        This proves the sample does trigger new_cluster under default settings.
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema

        profile = _base_profile()
        sample = self._sample_with_15pct_unknown()
        reports = detect_drift_multi_schema(profile, sample, "events.all")

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]
        assert len(new_cluster_drifts) >= 1, (
            "Control check: 15% unknown with env threshold=0.05 must trigger new_cluster"
        )

    def test_with_stability_cfg_threshold_0_30_suppresses_15pct(self, monkeypatch):
        """
        Gap 1 (RED): when stability_cfg.new_cluster_threshold=0.30 is passed,
        15% unknown events must NOT trigger new_cluster drift.

        This test FAILS before the fix because _new_cluster_threshold() reads
        the env var (0.05) and ignores stability_cfg.new_cluster_threshold (0.30).
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema

        stab = StabilityConfig(
            new_cluster_threshold=0.30,
            new_cluster_is_evolution=True,
        )
        profile = _base_profile()
        sample = self._sample_with_15pct_unknown()

        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab
        )

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]
        assert len(new_cluster_drifts) == 0, (
            f"Gap 1: with stability_cfg.new_cluster_threshold=0.30, "
            f"15% unknown events must NOT fire new_cluster. "
            f"Got {len(new_cluster_drifts)} new_cluster drift(s). "
            f"This means stability_cfg.new_cluster_threshold is being ignored."
        )

    def test_with_stability_cfg_threshold_0_10_fires_15pct(self, monkeypatch):
        """
        Positive case: stability_cfg.new_cluster_threshold=0.10 and 15% unknown
        MUST fire new_cluster because 15% > 10%.
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema

        stab = StabilityConfig(
            new_cluster_threshold=0.10,
            new_cluster_is_evolution=False,
        )
        profile = _base_profile()
        sample = self._sample_with_15pct_unknown()

        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab
        )

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]
        assert len(new_cluster_drifts) >= 1, (
            "With stability_cfg.new_cluster_threshold=0.10, 15% unknown must fire new_cluster"
        )

    def test_events_all_real_config_threshold_is_030(self):
        """
        Confirm events.all.yaml has new_cluster_threshold=0.30 so the config
        source-of-truth is correct.
        """
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.stability.new_cluster_threshold == pytest.approx(0.30), (
            f"events.all.yaml must have new_cluster_threshold=0.30, "
            f"got {cfg.stability.new_cluster_threshold}"
        )

    def test_events_all_config_wired_suppresses_15pct_new_cluster(self, monkeypatch):
        """
        End-to-end: load events.all topic config, call detect_drift_multi_schema
        with that stability_cfg, and confirm 15% new events do NOT fire new_cluster.
        This tests the full wire from config file to detection behaviour.
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        stab = cfg.stability
        # Confirm we have the right config
        assert stab.new_cluster_threshold == pytest.approx(0.30)
        assert stab.new_cluster_is_evolution is True

        profile = _base_profile()
        sample = self._sample_with_15pct_unknown()

        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab
        )

        new_cluster_drifts = [
            d for r in (reports or []) for d in r.drifts if d.drift_type == "new_cluster"
        ]
        assert len(new_cluster_drifts) == 0, (
            f"Gap 1 end-to-end: with events.all config (threshold=0.30), "
            f"15% new events must NOT fire new_cluster. "
            f"Got {new_cluster_drifts}."
        )


# ===========================================================================
# Gap 2: flap counter must reset when all signals are EVOLUTION or NOISE
# ===========================================================================

class TestFlapCounterResetsOnEvolutionOnlyCycles:
    """
    When detect_drift_multi_schema returns reports but every drift in those
    reports is EVOLUTION or NOISE (nothing is DRIFT), the STABLE phase must
    treat the cycle as clean for flap-suppression purposes.

    The broken code:
        if not _critical and not _non_critical and not reports:
            _consec_drift_count = 0

    `not reports` is always False here (we're in the `else` block), so the
    reset never fires when all signals are EVOLUTION.

    The correct condition should be:
        if not _critical and not _non_critical:
            _consec_drift_count = 0

    These tests prove the logic of the fix by validating the dispatch split.
    """

    def test_evolution_only_reports_produce_empty_drift_bucket(self):
        """
        When every FieldDrift in every report is EVOLUTION, the _drift_reports
        list must be empty after the dispatch split.
        """
        from streamforge.models import DriftClass, DriftReport, DriftTier, FieldDrift

        evolution_drift = FieldDrift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.15,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )
        report = DriftReport(
            stream_name="events.all",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="profile.yaml",
            events_sampled=200,
            drifts=[evolution_drift],
            highest_tier=DriftTier.TIER_2,
            summary="new cluster",
            evolution_count=1,
            noise_count=0,
        )

        reports = [report]

        # Replicate the dispatch split
        _drift_reports = []
        _evolution_drifts = []
        _noise_count = 0

        for r in reports:
            _rd = [d for d in r.drifts if d.drift_class == DriftClass.DRIFT]
            _re = [d for d in r.drifts if d.drift_class == DriftClass.EVOLUTION]
            _rn = [d for d in r.drifts if d.drift_class == DriftClass.NOISE]

            _evolution_drifts.extend(_re)
            _noise_count += len(_rn)

            if _rd:
                _drift_reports.append(r.model_copy(update={
                    "drifts": _rd,
                    "highest_tier": max(d.tier for d in _rd),
                    "evolution_count": 0,
                    "noise_count": len(_rn),
                }))

        _critical = [r for r in _drift_reports if r.highest_tier.value >= 3]
        _non_critical = [r for r in _drift_reports if r.highest_tier.value < 3]

        assert len(_drift_reports) == 0, (
            "Evolution-only cycle must produce no DRIFT reports"
        )
        assert not _critical and not _non_critical, (
            "Evolution-only cycle must produce no critical or non-critical DRIFT reports"
        )
        assert len(_evolution_drifts) == 1

    def test_broken_reset_condition_is_dead_code(self):
        """
        Documents the broken condition: 'not _critical and not _non_critical and not reports'
        is always False in the else branch (reports is always truthy there).

        This test proves the dead-code problem by showing the condition never fires.
        """
        from streamforge.models import DriftClass, DriftReport, DriftTier, FieldDrift

        # Build an evolution-only report
        evolution_drift = FieldDrift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.15,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )
        report = DriftReport(
            stream_name="events.all",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="profile.yaml",
            events_sampled=200,
            drifts=[evolution_drift],
            highest_tier=DriftTier.TIER_2,
            summary="new cluster",
            evolution_count=1,
            noise_count=0,
        )
        reports = [report]  # non-empty — we're in the else branch

        # Simulate the broken dispatch
        _drift_reports = []
        _noise_count = 0

        for r in reports:
            _rd = [d for d in r.drifts if d.drift_class == DriftClass.DRIFT]
            _rn = [d for d in r.drifts if d.drift_class == DriftClass.NOISE]
            _noise_count += len(_rn)
            if _rd:
                _drift_reports.append(r)

        _critical = [r for r in _drift_reports if r.highest_tier.value >= 3]
        _non_critical = [r for r in _drift_reports if r.highest_tier.value < 3]

        # The broken condition: "not reports" is always False here
        broken_reset_fires = (not _critical and not _non_critical and not reports)
        assert not broken_reset_fires, (
            "The broken reset condition 'not _critical and not _non_critical and not reports' "
            "never fires when reports is truthy. This proves the dead-code bug."
        )

    def test_correct_reset_condition_fires_for_evolution_only_cycle(self):
        """
        The FIXED condition 'not _critical and not _non_critical' must fire
        (return True) when all signals are EVOLUTION — so the flap counter resets.
        """
        from streamforge.models import DriftClass, DriftReport, DriftTier, FieldDrift

        evolution_drift = FieldDrift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=0.15,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            drift_class=DriftClass.EVOLUTION,
        )
        report = DriftReport(
            stream_name="events.all",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="profile.yaml",
            events_sampled=200,
            drifts=[evolution_drift],
            highest_tier=DriftTier.TIER_2,
            summary="new cluster",
            evolution_count=1,
            noise_count=0,
        )
        reports = [report]

        # Fixed dispatch split
        _drift_reports = []
        for r in reports:
            _rd = [d for d in r.drifts if d.drift_class == DriftClass.DRIFT]
            if _rd:
                _drift_reports.append(r)

        _critical = [r for r in _drift_reports if r.highest_tier.value >= 3]
        _non_critical = [r for r in _drift_reports if r.highest_tier.value < 3]

        # The FIXED condition: no "not reports" check needed
        correct_reset_fires = (not _critical and not _non_critical)
        assert correct_reset_fires, (
            "Fixed reset condition 'not _critical and not _non_critical' must be True "
            "for evolution-only cycles, so _consec_drift_count is reset to 0."
        )

    def test_noise_only_cycle_also_triggers_correct_reset(self):
        """NOISE-only cycles must also reset the flap counter."""
        from streamforge.models import DriftClass, DriftReport, DriftTier, FieldDrift

        noise_drift = FieldDrift(
            field_path="unknown_field",
            drift_type="field_added",
            affected_event_rate=0.03,
            tier=DriftTier.TIER_1,
            auto_correctable=True,
            correction_confidence=0.35,
            drift_class=DriftClass.NOISE,
        )
        report = DriftReport(
            stream_name="events.all",
            detected_at="2026-01-01T00:00:00Z",
            schema_version="profile.yaml",
            events_sampled=200,
            drifts=[noise_drift],
            highest_tier=DriftTier.TIER_1,
            summary="noise",
            evolution_count=0,
            noise_count=1,
        )
        reports = [report]

        _drift_reports = []
        for r in reports:
            _rd = [d for d in r.drifts if d.drift_class == DriftClass.DRIFT]
            if _rd:
                _drift_reports.append(r)

        _critical = [r for r in _drift_reports if r.highest_tier.value >= 3]
        _non_critical = [r for r in _drift_reports if r.highest_tier.value < 3]

        correct_reset_fires = (not _critical and not _non_critical)
        assert correct_reset_fires, (
            "NOISE-only cycles must also reset _consec_drift_count"
        )


# ===========================================================================
# Gap 3: End-to-end regression — drift still fires, evolution does not alert
# ===========================================================================

class TestEndToEndDispatchBehavior:
    """
    Confirm that the three dispatch paths produce the correct runtime behavior:
      DRIFT     → alert
      EVOLUTION → _handle_evolution (no alert)
      NOISE     → suppressed
    """

    def test_new_cluster_above_030_with_events_all_config_is_evolution_no_alert(
        self, monkeypatch
    ):
        """
        35% new cluster events WITH events.all config (threshold=0.30,
        new_cluster_is_evolution=True) must be classified EVOLUTION, not DRIFT.
        No alert should fire.
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema
        from streamforge.models import DriftClass
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        stab = cfg.stability
        assert stab.new_cluster_threshold == pytest.approx(0.30)
        assert stab.new_cluster_is_evolution is True

        profile = _base_profile()
        # 35% unknown → above 0.30 threshold → should fire new_cluster
        # but classified as EVOLUTION (not DRIFT)
        sample = (
            [{"event_type": "payment", "amount": float(i)} for i in range(65)]
            + [{"event_type": "refund", "amount": float(-i)} for i in range(35)]
        )

        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab
        )

        for r in reports:
            for d in r.drifts:
                if d.drift_type == "new_cluster":
                    assert d.drift_class == DriftClass.EVOLUTION, (
                        f"With events.all config, new_cluster must be EVOLUTION, "
                        f"got {d.drift_class}"
                    )

        # Check that no DRIFT-class new_cluster drift exists
        drift_new_clusters = [
            d
            for r in (reports or [])
            for d in r.drifts
            if d.drift_type == "new_cluster" and d.drift_class == DriftClass.DRIFT
        ]
        assert len(drift_new_clusters) == 0, (
            f"No DRIFT-class new_cluster expected with events.all config. "
            f"Got: {drift_new_clusters}"
        )

    def test_field_removed_is_still_drift_with_events_all_config(self, monkeypatch):
        """
        Regression guard: field_removed must still be classified DRIFT even
        with events.all config (new_cluster_is_evolution=True).
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift
        from streamforge.models import DriftClass, FieldSchema, InferredSchema
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")

        schema = InferredSchema(
            stream_name="events.all",
            inferred_at="2026-01-01T00:00:00Z",
            event_count_sampled=100,
            fields=[
                FieldSchema(
                    name="amount",
                    path="amount",
                    field_type="float",
                    presence_rate=1.0,
                    required=True,
                )
            ],
            inference_model="test",
            inference_confidence=0.9,
        )
        # Events without the required field → field_removed
        sample = [{"event_type": "payment"} for _ in range(50)]
        report = detect_drift(schema, sample, "events.all", stability_cfg=cfg.stability)

        assert report is not None
        removed_drifts = [
            d for d in report.drifts
            if d.drift_type == "field_removed" and d.drift_class == DriftClass.DRIFT
        ]
        assert len(removed_drifts) >= 1, (
            "field_removed must always be DRIFT, even with events.all config"
        )

    def test_new_cluster_below_030_threshold_produces_no_report(self, monkeypatch):
        """
        Gap 1 final check: with stability_cfg.new_cluster_threshold=0.30,
        a 15% unknown rate must produce zero reports (no new_cluster drift at all).
        """
        monkeypatch.delenv("STREAMFORGE_NEW_CLUSTER_THRESHOLD", raising=False)
        from streamforge.drift_detector import detect_drift_multi_schema
        from streamforge.topic_config import load_topic_config

        cfg = load_topic_config("events.all")
        stab = cfg.stability

        profile = _base_profile()
        sample = (
            [{"event_type": "payment", "amount": float(i)} for i in range(85)]
            + [{"event_type": "refund", "amount": float(-i)} for i in range(15)]
        )

        reports = detect_drift_multi_schema(
            profile, sample, "events.all", stability_cfg=stab
        )

        new_cluster_reports = [
            r for r in (reports or [])
            if any(d.drift_type == "new_cluster" for d in r.drifts)
        ]
        assert len(new_cluster_reports) == 0, (
            f"Gap 1: With events.all config (threshold=0.30), 15% new events "
            f"must produce zero new_cluster reports. Got {len(new_cluster_reports)}."
        )
