"""
False Discovery Rate (FDR) correction for multiple hypothesis testing.

Design philosophy (staff engineer notes):
  - At scale (100+ fields × 3-4 tests each), uncorrected p-values produce
    unacceptable false positive rates. With alpha=0.01 and 400 tests,
    expected false positives = 4 per cycle. FDR correction is mandatory.

  - Benjamini-Hochberg (BH) is the standard: controls FDR at level q while
    maintaining statistical power. More powerful than Bonferroni.

  - All functions are pure: no side effects, deterministic output.

  - We track both raw p-values and adjusted p-values for transparency.
    Operators can audit why a drift was suppressed.

References:
  - Benjamini & Hochberg (1995) "Controlling the False Discovery Rate"
  - Benjamini & Yekutieli (2001) for dependency assumptions
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FDRResult:
    """
    Result of FDR correction on a single hypothesis.

    Attributes:
        field_path:      Identifier for the field being tested.
        test_type:       Type of test ("presence", "type", "enum").
        raw_p_value:     Original p-value from statistical test.
        adjusted_p_value: BH-adjusted p-value.
        rank:            Rank in sorted p-value list (1 = smallest).
        is_significant:  True if adjusted_p_value < threshold.
        reason:          Human-readable explanation.
    """
    field_path: str
    test_type: str
    raw_p_value: float
    adjusted_p_value: float
    rank: int
    is_significant: bool
    reason: str = ""


@dataclass
class FDRCorrectionReport:
    """
    Summary of FDR correction across all tests in a drift detection cycle.

    Attributes:
        total_tests:       Number of hypotheses tested.
        significant_raw:   Tests significant before FDR correction.
        significant_adj:   Tests significant after FDR correction.
        suppressed_count:  Tests that were significant raw but not after FDR.
        fdr_threshold:     The q-value threshold used.
        results:           Per-test FDR results.
    """
    total_tests: int
    significant_raw: int
    significant_adj: int
    suppressed_count: int
    fdr_threshold: float
    results: list[FDRResult] = field(default_factory=list)

    @property
    def suppression_rate(self) -> float:
        """Fraction of raw significant tests that were suppressed by FDR."""
        if self.significant_raw == 0:
            return 0.0
        return self.suppressed_count / self.significant_raw


def benjamini_hochberg(
    p_values: Sequence[tuple[str, str, float]],  # (field_path, test_type, p_value)
    alpha: float = 0.01,
) -> FDRCorrectionReport:
    """
    Apply Benjamini-Hochberg FDR correction to a set of p-values.

    The BH procedure controls the expected proportion of false discoveries
    (false positives among rejected hypotheses) at level alpha.

    Algorithm:
      1. Sort p-values in ascending order: p(1) <= p(2) <= ... <= p(m)
      2. Find largest k such that p(k) <= (k/m) * alpha
      3. Reject all hypotheses with rank <= k

    Adjusted p-values:
      adj_p(i) = min(p(i) * m/i, 1.0), enforcing monotonicity from right.

    Args:
        p_values: List of (field_path, test_type, p_value) tuples.
        alpha:    FDR threshold (default 0.01 = control FDR at 1%).

    Returns:
        FDRCorrectionReport with per-test results and summary statistics.
    """
    if not p_values:
        return FDRCorrectionReport(
            total_tests=0,
            significant_raw=0,
            significant_adj=0,
            suppressed_count=0,
            fdr_threshold=alpha,
            results=[],
        )

    m = len(p_values)

    # Sort by p-value, keeping track of original index
    indexed = [(i, fp, tt, pv) for i, (fp, tt, pv) in enumerate(p_values)]
    sorted_by_p = sorted(indexed, key=lambda x: x[3])  # sort by p-value

    # Compute adjusted p-values with monotonicity enforcement
    # adj_p(i) = min(p(i) * m / rank, adj_p(i+1), 1.0)
    adjusted = [0.0] * m
    prev_adj = 1.0

    for rank_idx in range(m - 1, -1, -1):  # iterate from largest to smallest
        orig_idx, field_path, test_type, raw_p = sorted_by_p[rank_idx]
        rank = rank_idx + 1  # 1-indexed rank

        # BH adjusted p-value
        adj_p = min(raw_p * m / rank, prev_adj, 1.0)
        adjusted[rank_idx] = adj_p
        prev_adj = adj_p

    # Build results
    results: list[FDRResult] = []
    significant_raw = 0
    significant_adj = 0

    for rank_idx, (_orig_idx, field_path, test_type, raw_p) in enumerate(sorted_by_p):
        rank = rank_idx + 1
        adj_p = adjusted[rank_idx]

        is_raw_sig = raw_p < alpha
        is_adj_sig = adj_p < alpha

        if is_raw_sig:
            significant_raw += 1
        if is_adj_sig:
            significant_adj += 1

        if is_raw_sig and not is_adj_sig:
            reason = f"Suppressed by FDR: raw p={raw_p:.4f} -> adj p={adj_p:.4f} >= {alpha}"
        elif is_adj_sig:
            reason = f"Significant after FDR: adj p={adj_p:.4f} < {alpha}"
        else:
            reason = f"Not significant: raw p={raw_p:.4f}"

        results.append(FDRResult(
            field_path=field_path,
            test_type=test_type,
            raw_p_value=raw_p,
            adjusted_p_value=adj_p,
            rank=rank,
            is_significant=is_adj_sig,
            reason=reason,
        ))

    suppressed = significant_raw - significant_adj

    if suppressed > 0:
        logger.info(
            "FDR correction: %d/%d tests suppressed (%.1f%% reduction in alerts)",
            suppressed, significant_raw, 100 * suppressed / max(significant_raw, 1)
        )

    return FDRCorrectionReport(
        total_tests=m,
        significant_raw=significant_raw,
        significant_adj=significant_adj,
        suppressed_count=suppressed,
        fdr_threshold=alpha,
        results=results,
    )


def filter_significant(
    report: FDRCorrectionReport,
) -> dict[tuple[str, str], FDRResult]:
    """
    Extract only significant results from FDR correction report.

    Returns:
        Dict mapping (field_path, test_type) -> FDRResult for significant tests.
    """
    return {
        (r.field_path, r.test_type): r
        for r in report.results
        if r.is_significant
    }


# ---------------------------------------------------------------------------
# Validation utilities for testing at scale
# ---------------------------------------------------------------------------

def validate_fdr_at_scale(
    n_fields: int = 100,
    n_tests_per_field: int = 3,
    null_proportion: float = 0.95,  # 95% of tests are true nulls (no real drift)
    alpha: float = 0.01,
    n_simulations: int = 1000,
    seed: int | None = None,
) -> dict:
    """
    Monte Carlo validation of FDR control at scale.

    Simulates a scenario where most fields have no drift (null hypothesis true)
    and validates that FDR is controlled at the specified level.

    Args:
        n_fields:         Number of fields in schema.
        n_tests_per_field: Tests per field (presence, type, enum).
        null_proportion:  Fraction of tests where null is true (no drift).
        alpha:            FDR threshold.
        n_simulations:    Number of Monte Carlo iterations.

    Returns:
        Dictionary with:
          - observed_fdr: Actual FDR across simulations.
          - target_fdr: The alpha level.
          - power: Proportion of true alternatives detected.
          - is_valid: True if observed_fdr <= target_fdr.
    """
    import random

    # Local RNG so a caller can make the Monte Carlo run reproducible (e.g. CI)
    # without disturbing global random state. seed=None preserves prior behaviour.
    rng = random.Random(seed)

    total_tests = n_fields * n_tests_per_field
    n_null = int(total_tests * null_proportion)
    n_alt = total_tests - n_null

    total_false_discoveries = 0
    total_discoveries = 0
    total_true_discoveries = 0

    for _ in range(n_simulations):
        p_values = []
        true_alt_indices = set(rng.sample(range(total_tests), n_alt))

        for i in range(total_tests):
            field_path = f"field_{i // n_tests_per_field}"
            test_type = ["presence", "type", "enum"][i % n_tests_per_field]

            if i in true_alt_indices:
                # True alternative: realistic p-values from actual drift.
                # Z-test with 200 samples and 20% rate shift produces p ~ 1e-6.
                # Use beta(0.3, 100) to model this: median ~0.0003, 90th pct ~0.01
                p = rng.betavariate(0.3, 100)
            else:
                # True null: p-value uniform on [0, 1]
                p = rng.random()

            p_values.append((field_path, test_type, p))

        report = benjamini_hochberg(p_values, alpha=alpha)

        # Count false discoveries (null hypotheses incorrectly rejected)
        for r in report.results:
            if r.is_significant:
                total_discoveries += 1
                idx = int(r.field_path.split("_")[1]) * n_tests_per_field
                idx += ["presence", "type", "enum"].index(r.test_type)
                if idx not in true_alt_indices:
                    total_false_discoveries += 1
                else:
                    total_true_discoveries += 1

    observed_fdr = total_false_discoveries / max(total_discoveries, 1)
    power = total_true_discoveries / max(n_alt * n_simulations, 1)

    return {
        "total_tests_per_sim": total_tests,
        "null_proportion": null_proportion,
        "n_simulations": n_simulations,
        "target_fdr": alpha,
        "observed_fdr": round(observed_fdr, 4),
        "power": round(power, 4),
        "is_valid": observed_fdr <= alpha + 0.005,  # small tolerance for simulation variance
        "total_discoveries": total_discoveries,
        "total_false_discoveries": total_false_discoveries,
    }
