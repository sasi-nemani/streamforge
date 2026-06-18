"""Tests for the Expected Calibration Error (ECE) computation."""
from __future__ import annotations

import pytest

from streamforge.eval.calibration import expected_calibration_error
from streamforge.eval.types import CalibrationResult, ReliabilityBin


def test_empty_input_yields_zero_ece_and_no_bins():
    result = expected_calibration_error([])
    assert isinstance(result, CalibrationResult)
    assert result.ece == 0.0
    assert result.bins == ()
    assert result.n_samples == 0


def test_perfectly_calibrated_input_has_near_zero_ece():
    # Confidence 0.9, correct exactly 90% of the time -> bin accuracy == conf.
    pairs = [(0.9, True)] * 9 + [(0.9, False)] * 1
    result = expected_calibration_error(pairs)
    assert result.ece == pytest.approx(0.0, abs=1e-9)
    assert result.n_samples == 10
    # All ten predictions land in the same bin (0.9 -> bin index 9).
    assert len(result.bins) == 1
    b = result.bins[0]
    assert b.mean_confidence == pytest.approx(0.9)
    assert b.accuracy == pytest.approx(0.9)
    assert b.count == 10


def test_perfectly_calibrated_across_multiple_bins():
    # Two bins, each internally perfectly calibrated.
    pairs = (
        [(0.9, True)] * 9 + [(0.9, False)] * 1  # bin 9: acc 0.9, conf 0.9
        + [(0.1, True)] * 1 + [(0.1, False)] * 9  # bin 0: acc 0.1, conf 0.1
    )
    result = expected_calibration_error(pairs)
    assert result.ece == pytest.approx(0.0, abs=1e-9)
    assert len(result.bins) == 2
    # Bins ordered by lower edge.
    assert result.bins[0].lower < result.bins[1].lower


def test_overconfident_input_has_ece_near_half():
    # Confidence 1.0 but only 50% correct -> |0.5 - 1.0| = 0.5.
    pairs = [(1.0, True)] * 50 + [(1.0, False)] * 50
    result = expected_calibration_error(pairs)
    assert result.ece == pytest.approx(0.5)
    assert result.n_samples == 100
    assert len(result.bins) == 1
    assert result.bins[0].accuracy == pytest.approx(0.5)
    assert result.bins[0].mean_confidence == pytest.approx(1.0)


def test_confidence_exactly_one_lands_in_last_bin():
    result = expected_calibration_error([(1.0, True)], n_bins=10)
    assert len(result.bins) == 1
    b = result.bins[0]
    assert b.count == 1
    # Last bin of 10 equal-width bins is [0.9, 1.0].
    assert b.lower == pytest.approx(0.9)
    assert b.upper == pytest.approx(1.0)


def test_bin_counts_sum_to_n_samples():
    pairs = [
        (0.05, True),
        (0.15, False),
        (0.35, True),
        (0.55, False),
        (0.85, True),
        (0.95, False),
        (1.0, True),
        (0.0, False),
    ]
    result = expected_calibration_error(pairs)
    assert sum(b.count for b in result.bins) == result.n_samples
    assert result.n_samples == len(pairs)


def test_bins_are_ordered_by_lower_edge():
    pairs = [(0.95, True), (0.05, False), (0.55, True), (0.35, False)]
    result = expected_calibration_error(pairs)
    lowers = [b.lower for b in result.bins]
    assert lowers == sorted(lowers)


def test_only_non_empty_bins_included():
    # Everything in one bin; expect a single bin, not ten.
    pairs = [(0.42, True), (0.45, False), (0.49, True)]
    result = expected_calibration_error(pairs, n_bins=10)
    assert len(result.bins) == 1
    assert result.bins[0].count == 3


def test_out_of_range_confidences_are_clamped():
    # Negative clamps to 0.0 (bin 0); >1 clamps to 1.0 (last bin).
    pairs = [(-0.5, True), (1.7, False)]
    result = expected_calibration_error(pairs, n_bins=10)
    assert all(isinstance(b, ReliabilityBin) for b in result.bins)
    assert result.n_samples == 2
    # One sample in the first bin, one in the last.
    lowers = sorted(b.lower for b in result.bins)
    assert lowers[0] == pytest.approx(0.0)
    assert lowers[-1] == pytest.approx(0.9)
    # The clamped-to-1.0 sample contributes mean_confidence 1.0 in its bin.
    last = max(result.bins, key=lambda b: b.lower)
    assert last.mean_confidence == pytest.approx(1.0)


def test_invalid_n_bins_raises():
    with pytest.raises(ValueError):
        expected_calibration_error([(0.5, True)], n_bins=0)


def test_general_ece_value_is_weighted_gap():
    # Bin A: 0.8 conf, 2 samples, 1 correct -> acc 0.5, gap 0.3.
    # Bin B: 0.2 conf, 8 samples, 8 correct -> acc 1.0, gap 0.8.
    pairs = [(0.8, True), (0.8, False)] + [(0.2, True)] * 8
    result = expected_calibration_error(pairs)
    expected = (2 / 10) * 0.3 + (8 / 10) * 0.8
    assert result.ece == pytest.approx(expected)
