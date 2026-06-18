"""
Unit tests for statistical_tests.py

Design principles:
  - Test the math, not the system. No I/O, no mocks of business logic.
  - Each test verifies a specific statistical property or edge case.
  - Golden values computed analytically or cross-verified with scipy
    (scipy is only used to generate expected values, NOT as a runtime dep).
  - We test that the p-value ordering is correct even if the exact value
    differs slightly from the analytic answer (due to approximation).
"""


from streamforge.statistical_tests import (
    PSI_SLIGHT,
    TestResult,
    binomial_z_test,
    chi_squared_test,
    psi,
    summarise_field_tests,
)

# ---------------------------------------------------------------------------
# PSI tests
# ---------------------------------------------------------------------------

class TestPSI:

    def test_identical_distributions_gives_zero(self):
        data = [float(x) for x in range(100)]
        result = psi(data, data)
        assert result.statistic < 0.01
        assert not result.is_significant

    def test_clearly_drifted_distribution_flagged(self):
        # Baseline: values 0-99; Observed: values 200-299 — completely different
        baseline = [float(x) for x in range(100)]
        observed = [float(x) for x in range(200, 300)]
        result = psi(baseline, observed, threshold=PSI_SLIGHT)
        assert result.is_significant
        assert result.statistic > PSI_SLIGHT

    def test_slight_drift_below_threshold(self):
        # Small shift — both drawn from similar range
        import random
        rng = random.Random(42)
        baseline = [rng.gauss(0, 1) for _ in range(500)]
        observed = [rng.gauss(0.1, 1) for _ in range(500)]  # tiny mean shift
        result = psi(baseline, observed, threshold=PSI_SLIGHT)
        # Very small shift should not exceed PSI_SLIGHT
        assert result.statistic < PSI_SLIGHT

    def test_returns_psi_test_name(self):
        data = [1.0, 2.0, 3.0]
        result = psi(data, data)
        assert result.test_name == "psi"

    def test_p_value_is_none_for_psi(self):
        data = [1.0, 2.0, 3.0]
        result = psi(data, data)
        assert result.p_value is None

    def test_empty_baseline_returns_not_significant(self):
        result = psi([], [1.0, 2.0])
        assert not result.is_significant
        assert result.reason != ""

    def test_empty_observed_returns_not_significant(self):
        result = psi([1.0, 2.0, 3.0], [])
        assert not result.is_significant
        assert result.reason != ""

    def test_single_baseline_value_returns_not_significant(self):
        result = psi([5.0], [5.0, 6.0])
        assert not result.is_significant
        assert result.reason != ""

    def test_all_identical_baseline_returns_not_significant(self):
        baseline = [1.0] * 100
        observed = [1.0, 2.0, 3.0]
        result = psi(baseline, observed)
        assert not result.is_significant

    def test_custom_threshold(self):
        baseline = [float(x) for x in range(100)]
        observed = [float(x) + 5 for x in range(100)]
        # With a very tight threshold, this should be significant
        result_tight = psi(baseline, observed, threshold=0.001)
        result_loose = psi(baseline, observed, threshold=10.0)
        assert result_tight.is_significant
        assert not result_loose.is_significant

    def test_effect_size_equals_statistic(self):
        baseline = [float(x) for x in range(100)]
        observed = [float(x) for x in range(50, 150)]
        result = psi(baseline, observed)
        assert result.effect_size == result.statistic

    def test_psi_non_negative(self):
        # PSI is always >= 0 by construction
        import random
        rng = random.Random(0)
        for _ in range(20):
            base = [rng.gauss(0, 1) for _ in range(100)]
            obs = [rng.gauss(rng.uniform(-2, 2), 1) for _ in range(100)]
            result = psi(base, obs)
            assert result.statistic >= 0.0, f"Negative PSI: {result.statistic}"

    def test_larger_shift_produces_larger_psi(self):
        baseline = [float(x) for x in range(200)]
        small_shift = [float(x) + 5 for x in range(200)]
        large_shift = [float(x) + 50 for x in range(200)]
        r_small = psi(baseline, small_shift)
        r_large = psi(baseline, large_shift)
        assert r_large.statistic > r_small.statistic


# ---------------------------------------------------------------------------
# Binomial z-test tests
# ---------------------------------------------------------------------------

class TestBinomialZTest:

    def test_no_change_is_not_significant(self):
        # Baseline 90%, observed 90% of 200 events
        result = binomial_z_test(
            baseline_rate=0.90,
            observed_count=180,
            observed_total=200,
        )
        assert not result.is_significant
        # z should be close to 0
        assert abs(result.statistic) < 1.0

    def test_massive_drop_is_significant(self):
        # Baseline 95%, observed 10% of 500 events
        result = binomial_z_test(
            baseline_rate=0.95,
            observed_count=50,
            observed_total=500,
        )
        assert result.is_significant
        assert result.p_value < 0.001

    def test_returns_binomial_z_test_name(self):
        result = binomial_z_test(0.5, 50, 100)
        assert result.test_name == "binomial_z"

    def test_p_value_is_not_none(self):
        result = binomial_z_test(0.5, 50, 100)
        assert result.p_value is not None

    def test_zero_total_returns_not_significant(self):
        result = binomial_z_test(0.9, 0, 0)
        assert not result.is_significant
        assert result.reason != ""

    def test_p_value_range(self):
        for rate in [0.1, 0.5, 0.9]:
            for count in [10, 50, 90]:
                result = binomial_z_test(rate, count, 100)
                assert 0.0 <= result.p_value <= 1.0, (
                    f"p_value={result.p_value} out of range for rate={rate}, count={count}"
                )

    def test_effect_size_is_absolute_rate_difference(self):
        result = binomial_z_test(0.90, 60, 100)  # observed 60%
        assert abs(result.effect_size - 0.30) < 1e-9

    def test_degenerate_baseline_zero_any_presence_is_significant(self):
        # Field was never present in baseline, now appears
        result = binomial_z_test(0.0, 50, 100)
        assert result.is_significant

    def test_degenerate_baseline_one_any_absence_is_significant(self):
        # Field was always present, now missing from some
        result = binomial_z_test(1.0, 90, 100)
        assert result.is_significant

    def test_degenerate_baseline_matches_not_significant(self):
        result = binomial_z_test(0.0, 0, 100)
        assert not result.is_significant

    def test_alpha_controls_sensitivity(self):
        # Rate changed from 0.8 to 0.7 in 100 events — borderline
        result_strict = binomial_z_test(0.80, 70, 100, alpha=0.001)
        result_loose = binomial_z_test(0.80, 70, 100, alpha=0.5)
        # Looser alpha means more likely to flag significant
        if result_strict.p_value is not None and result_loose.p_value is not None:
            assert result_loose.is_significant or not result_strict.is_significant

    def test_z_is_negative_when_observed_below_baseline(self):
        result = binomial_z_test(0.90, 60, 100)  # 60% < 90%
        assert result.statistic < 0

    def test_z_is_positive_when_observed_above_baseline(self):
        result = binomial_z_test(0.50, 80, 100)  # 80% > 50%
        assert result.statistic > 0

    def test_larger_sample_more_sensitive(self):
        # Same rate shift, but larger n → should have smaller p-value
        small_n = binomial_z_test(0.90, 81, 100)    # 81/100 = 81% vs 90% baseline
        large_n = binomial_z_test(0.90, 810, 1000)  # 810/1000 = 81% vs 90% baseline
        if small_n.p_value and large_n.p_value:
            assert large_n.p_value < small_n.p_value


# ---------------------------------------------------------------------------
# Chi-squared test tests
# ---------------------------------------------------------------------------

class TestChiSquaredTest:

    def test_identical_distributions_not_significant(self):
        base = {"string": 80, "integer": 20}
        obs = {"string": 80, "integer": 20}
        result = chi_squared_test(base, obs)
        assert not result.is_significant

    def test_proportionally_identical_not_significant(self):
        # Same proportions, different totals
        base = {"A": 100, "B": 100}
        obs = {"A": 200, "B": 200}
        result = chi_squared_test(base, obs)
        assert not result.is_significant

    def test_extreme_shift_is_significant(self):
        # Was almost all A, now almost all B — both categories exist in baseline
        base = {"A": 490, "B": 10}
        obs = {"A": 10, "B": 490}
        result = chi_squared_test(base, obs, min_expected=1.0)
        assert result.is_significant

    def test_returns_chi_squared_test_name(self):
        result = chi_squared_test({"A": 10}, {"A": 10})
        assert result.test_name == "chi_squared"

    def test_p_value_range(self):
        base = {"string": 80, "integer": 20}
        obs = {"string": 60, "integer": 40}
        result = chi_squared_test(base, obs)
        assert result.p_value is not None
        assert 0.0 <= result.p_value <= 1.0

    def test_new_category_in_observed_detected(self):
        # A new type appears that was not in baseline
        base = {"string": 100}
        obs = {"string": 80, "integer": 20}
        result = chi_squared_test(base, obs, min_expected=1.0)
        assert result.is_significant

    def test_empty_baseline_returns_not_significant(self):
        result = chi_squared_test({}, {"A": 10})
        assert not result.is_significant
        assert result.reason != ""

    def test_empty_observed_returns_not_significant(self):
        result = chi_squared_test({"A": 10}, {})
        assert not result.is_significant
        assert result.reason != ""

    def test_cramers_v_in_range(self):
        base = {"string": 80, "integer": 20}
        obs = {"string": 50, "integer": 50}
        result = chi_squared_test(base, obs, min_expected=1.0)
        assert 0.0 <= result.effect_size <= 1.0

    def test_larger_shift_larger_chi2(self):
        base = {"A": 100, "B": 100}
        small_shift = {"A": 90, "B": 110}
        large_shift = {"A": 10, "B": 190}
        r_small = chi_squared_test(base, small_shift, min_expected=1.0)
        r_large = chi_squared_test(base, large_shift, min_expected=1.0)
        assert r_large.statistic > r_small.statistic

    def test_single_category_collapses_gracefully(self):
        # Only one category — chi-sq not applicable (0 df)
        base = {"string": 100}
        obs = {"string": 90}
        result = chi_squared_test(base, obs)
        # Should return not-significant with reason, not raise
        assert not result.is_significant

    def test_alpha_controls_threshold(self):
        base = {"A": 100, "B": 100}
        obs = {"A": 80, "B": 120}
        result_strict = chi_squared_test(base, obs, alpha=0.0001, min_expected=1.0)
        result_loose = chi_squared_test(base, obs, alpha=0.5, min_expected=1.0)
        # At least: loose alpha is >= strict in terms of significance
        if result_strict.p_value and result_loose.p_value:
            assert result_loose.is_significant or not result_strict.is_significant


# ---------------------------------------------------------------------------
# summarise_field_tests tests
# ---------------------------------------------------------------------------

class TestSummariseFieldTests:

    def _make_result(self, significant: bool, effect: float, name: str) -> TestResult:
        return TestResult(
            is_significant=significant,
            statistic=1.0,
            p_value=0.001 if significant else 0.5,
            effect_size=effect,
            reason="",
            test_name=name,
        )

    def test_no_tests_no_drift(self):
        summary = summarise_field_tests("foo.bar", [])
        assert not summary.drift_detected
        assert summary.dominant_test is None
        assert summary.max_effect == 0.0

    def test_all_non_significant_no_drift(self):
        results = [
            self._make_result(False, 0.05, "psi"),
            self._make_result(False, 0.03, "binomial_z"),
        ]
        summary = summarise_field_tests("foo.bar", results)
        assert not summary.drift_detected
        assert summary.dominant_test is None

    def test_one_significant_triggers_drift(self):
        results = [
            self._make_result(False, 0.05, "psi"),
            self._make_result(True, 0.40, "binomial_z"),
        ]
        summary = summarise_field_tests("foo.bar", results)
        assert summary.drift_detected
        assert summary.dominant_test == "binomial_z"

    def test_dominant_test_is_highest_effect(self):
        results = [
            self._make_result(True, 0.10, "psi"),
            self._make_result(True, 0.80, "chi_squared"),
        ]
        summary = summarise_field_tests("foo.bar", results)
        assert summary.dominant_test == "chi_squared"
        assert summary.max_effect == 0.80

    def test_field_path_preserved(self):
        summary = summarise_field_tests("user.email", [])
        assert summary.field_path == "user.email"

    def test_max_effect_from_non_significant_when_no_significant(self):
        results = [
            self._make_result(False, 0.05, "psi"),
            self._make_result(False, 0.12, "binomial_z"),
        ]
        summary = summarise_field_tests("foo", results)
        assert summary.max_effect == 0.12


# ---------------------------------------------------------------------------
# Normal survival function tests (internal math)
# ---------------------------------------------------------------------------

class TestNormalSurvival:

    def test_z_zero_is_half(self):
        from streamforge.statistical_tests import _normal_survival
        # P(Z > 0) = 0.5 exactly
        assert abs(_normal_survival(0.0) - 0.5) < 1e-10

    def test_z_1_96_is_approximately_0_025(self):
        from streamforge.statistical_tests import _normal_survival
        # Standard: P(Z > 1.96) ≈ 0.025 (one-tail)
        assert abs(_normal_survival(1.96) - 0.025) < 0.001

    def test_z_2_576_is_approximately_0_005(self):
        from streamforge.statistical_tests import _normal_survival
        assert abs(_normal_survival(2.576) - 0.005) < 0.001

    def test_symmetry(self):
        from streamforge.statistical_tests import _normal_survival
        # P(Z > z) + P(Z > -z) = 1
        for z in [0.5, 1.0, 2.0, 3.0]:
            total = _normal_survival(z) + _normal_survival(-z)
            assert abs(total - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Chi-squared survival function tests (internal math)
# ---------------------------------------------------------------------------

class TestChi2Survival:

    def test_zero_input_returns_one(self):
        from streamforge.statistical_tests import _chi2_survival
        assert _chi2_survival(0.0, 1) == 1.0

    def test_known_value_df1(self):
        from streamforge.statistical_tests import _chi2_survival
        # chi2(1df) CDF at 3.84 ≈ 0.05 (p-value ≈ 0.05) — standard stats table
        p = _chi2_survival(3.84, 1)
        assert abs(p - 0.05) < 0.005

    def test_known_value_df2(self):
        from streamforge.statistical_tests import _chi2_survival
        # chi2(2df) at 5.99 → p ≈ 0.05
        p = _chi2_survival(5.99, 2)
        assert abs(p - 0.05) < 0.005

    def test_p_value_in_range(self):
        from streamforge.statistical_tests import _chi2_survival
        for df in [1, 2, 5, 10]:
            for x in [0.0, 1.0, 5.0, 20.0]:
                p = _chi2_survival(x, df)
                assert 0.0 <= p <= 1.0, f"Out of range: df={df}, x={x}, p={p}"

    def test_larger_x_smaller_p(self):
        from streamforge.statistical_tests import _chi2_survival
        for df in [1, 3, 5]:
            p_small = _chi2_survival(1.0, df)
            p_large = _chi2_survival(10.0, df)
            assert p_small > p_large
