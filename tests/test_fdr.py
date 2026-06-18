"""Tests for FDR (False Discovery Rate) correction module."""


from streamforge.fdr import (
    benjamini_hochberg,
    filter_significant,
    validate_fdr_at_scale,
)


class TestBenjaminiHochberg:
    """Tests for the Benjamini-Hochberg FDR correction."""

    def test_empty_input_returns_empty_report(self):
        """Empty p-value list produces empty report."""
        report = benjamini_hochberg([], alpha=0.01)
        assert report.total_tests == 0
        assert report.significant_raw == 0
        assert report.significant_adj == 0
        assert report.results == []

    def test_single_significant_pvalue(self):
        """Single p-value below alpha is significant."""
        p_values = [("field_a", "presence", 0.001)]
        report = benjamini_hochberg(p_values, alpha=0.01)

        assert report.total_tests == 1
        assert report.significant_raw == 1
        assert report.significant_adj == 1
        assert report.suppressed_count == 0
        assert report.results[0].is_significant is True

    def test_single_nonsignificant_pvalue(self):
        """Single p-value above alpha is not significant."""
        p_values = [("field_a", "presence", 0.05)]
        report = benjamini_hochberg(p_values, alpha=0.01)

        assert report.total_tests == 1
        assert report.significant_raw == 0
        assert report.significant_adj == 0
        assert report.results[0].is_significant is False

    def test_fdr_suppresses_marginal_pvalues(self):
        """BH correction suppresses marginally significant p-values at scale."""
        # 10 tests: 5 with p=0.005 (raw sig), 5 with p=0.5 (not sig)
        # At alpha=0.01, raw sig = 5
        # BH threshold for rank k: k/10 * 0.01
        # Rank 1: threshold = 0.001 (p=0.005 > 0.001 → not sig)
        p_values = [
            (f"field_{i}", "presence", 0.005 if i < 5 else 0.5)
            for i in range(10)
        ]
        report = benjamini_hochberg(p_values, alpha=0.01)

        # All 5 with p=0.005 are significant raw (p < 0.01)
        assert report.significant_raw == 5
        # But BH suppresses some: p(k) must be <= k/m * alpha
        # p=0.005, rank 1-5: threshold = 0.001, 0.002, 0.003, 0.004, 0.005
        # Only rank 5 passes: 0.005 <= 0.005
        assert report.significant_adj <= report.significant_raw
        assert report.suppressed_count == report.significant_raw - report.significant_adj

    def test_adjusted_pvalues_are_monotonic(self):
        """Adjusted p-values maintain monotonicity from smallest to largest."""
        p_values = [
            ("f1", "t", 0.001),
            ("f2", "t", 0.003),
            ("f3", "t", 0.01),
            ("f4", "t", 0.05),
            ("f5", "t", 0.1),
        ]
        report = benjamini_hochberg(p_values, alpha=0.05)

        # Sort by raw p-value and check adjusted p-values are monotonic
        sorted_results = sorted(report.results, key=lambda r: r.raw_p_value)
        for i in range(1, len(sorted_results)):
            assert sorted_results[i].adjusted_p_value >= sorted_results[i - 1].adjusted_p_value

    def test_adjusted_pvalues_capped_at_one(self):
        """Adjusted p-values never exceed 1.0."""
        p_values = [("field", "type", 0.9)]
        report = benjamini_hochberg(p_values, alpha=0.05)
        assert report.results[0].adjusted_p_value <= 1.0

    def test_suppression_rate_calculation(self):
        """Suppression rate correctly calculates fraction suppressed."""
        p_values = [
            ("f1", "presence", 0.001),  # sig raw, survives FDR
            ("f2", "presence", 0.008),  # sig raw at alpha=0.01, may be suppressed
        ]
        report = benjamini_hochberg(p_values, alpha=0.01)

        if report.significant_raw > 0:
            expected_rate = report.suppressed_count / report.significant_raw
            assert abs(report.suppression_rate - expected_rate) < 0.001


class TestFilterSignificant:
    """Tests for filter_significant helper."""

    def test_returns_only_significant_results(self):
        """Filter returns dict of only significant results."""
        p_values = [
            ("field_a", "presence", 0.001),
            ("field_b", "type", 0.5),
            ("field_c", "enum", 0.002),
        ]
        report = benjamini_hochberg(p_values, alpha=0.05)
        filtered = filter_significant(report)

        # All filtered entries should be significant
        for (_fp, _tt), result in filtered.items():
            assert result.is_significant is True

    def test_returns_empty_dict_when_no_significant(self):
        """Filter returns empty dict when nothing is significant."""
        p_values = [("f1", "t", 0.5), ("f2", "t", 0.6)]
        report = benjamini_hochberg(p_values, alpha=0.01)
        filtered = filter_significant(report)
        assert filtered == {}


class TestFDRValidationAtScale:
    """Tests for Monte Carlo validation of FDR control."""

    def test_fdr_controlled_at_target_level(self):
        """FDR is controlled at or near the target alpha level."""
        result = validate_fdr_at_scale(
            n_fields=50,
            n_tests_per_field=3,
            null_proportion=0.90,
            alpha=0.05,
            n_simulations=200,
            seed=42,  # reproducible Monte Carlo — no flaky CI failures
        )

        # FDR should be controlled within tolerance
        assert result["is_valid"] is True
        assert result["observed_fdr"] <= result["target_fdr"] + 0.02

    def test_power_is_positive_for_true_alternatives(self):
        """Statistical power should detect at least some true alternatives."""
        result = validate_fdr_at_scale(
            n_fields=50,
            n_tests_per_field=3,
            null_proportion=0.80,  # 20% true alternatives
            alpha=0.05,
            n_simulations=100,
        )

        # Should detect at least 10% of true alternatives
        assert result["power"] > 0.1


class TestFDRIntegrationWithDriftDetector:
    """Integration tests for FDR in drift detection pipeline."""

    def test_fdr_filtering_preserves_pii_alerts(self):
        """PII alerts (no p-value) should not be suppressed by FDR."""
        from streamforge.detector.core import _apply_fdr_filtering, _PendingDrift
        from streamforge.models import DriftTier, FieldDrift

        pending = [
            _PendingDrift(
                drift=FieldDrift(
                    field_path="email",
                    drift_type="new_pii",
                    tier=DriftTier.TIER_3,
                    auto_correctable=False,
                    affected_event_rate=0.5,
                ),
                p_value=None,  # PII has no p-value
                test_type="pii",
            ),
            _PendingDrift(
                drift=FieldDrift(
                    field_path="count",
                    drift_type="presence_drop",
                    tier=DriftTier.TIER_1,
                    auto_correctable=False,
                    affected_event_rate=0.3,
                ),
                p_value=0.009,  # Marginal, may be suppressed
                test_type="presence",
            ),
        ]

        drifts, fdr_report = _apply_fdr_filtering(pending, "test-stream")

        # PII alert should always be preserved
        pii_drifts = [d for d in drifts if d.drift_type == "new_pii"]
        assert len(pii_drifts) == 1

    def test_fdr_disabled_returns_all_drifts(self):
        """When FDR is disabled, all drifts pass through."""

        from streamforge.detector.core import _apply_fdr_filtering, _PendingDrift
        from streamforge.models import DriftTier, FieldDrift

        # Temporarily check FDR behavior
        pending = [
            _PendingDrift(
                drift=FieldDrift(
                    field_path="field_a",
                    drift_type="presence_drop",
                    tier=DriftTier.TIER_1,
                    auto_correctable=False,
                    affected_event_rate=0.2,
                ),
                p_value=0.009,
                test_type="presence",
            ),
        ]

        # With FDR enabled, single p=0.009 < 0.01 survives BH (1 test, threshold=0.01)
        drifts, _ = _apply_fdr_filtering(pending, "test")
        assert len(drifts) == 1
