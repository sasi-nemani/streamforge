"""Confidence calibration for the evaluation harness.

A well-calibrated model that reports 0.9 confidence should be correct ~90% of
the time. We measure this with the Expected Calibration Error (ECE): bin the
predictions by reported confidence, then compare each bin's mean confidence to
its empirical accuracy. The closer they track, the lower the ECE.

Only ``expected_calibration_error`` is public — ``runner.py`` calls it.
"""
from __future__ import annotations

from streamforge.eval.types import CalibrationResult, ReliabilityBin


def _clamp_unit(value: float) -> float:
    """Clamp a confidence into [0, 1]. Out-of-range inputs are pulled in."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _bin_index(confidence: float, n_bins: int) -> int:
    """Map a clamped confidence in [0, 1] to a bin index in [0, n_bins - 1].

    Bins are equal-width over [0, 1]. ``confidence == 1.0`` is assigned to the
    top bin rather than a phantom ``n_bins``-th bin.
    """
    idx = int(confidence * n_bins)
    if idx >= n_bins:
        idx = n_bins - 1
    return idx


def expected_calibration_error(
    pairs: list[tuple[float, bool]], n_bins: int = 10
) -> CalibrationResult:
    """Compute the Expected Calibration Error over (confidence, correct) pairs.

    Args:
        pairs: list of ``(confidence, was_correct)`` where ``confidence`` is the
            model's reported confidence (clamped into [0, 1]) and ``was_correct``
            is whether that prediction matched ground truth.
        n_bins: number of equal-width bins partitioning [0, 1].

    Returns:
        A ``CalibrationResult`` whose ``bins`` contains only non-empty bins,
        ordered by lower edge, and whose ``ece`` is the count-weighted mean
        absolute gap between bin accuracy and bin mean confidence. Empty input
        yields ``ece=0.0``, ``bins=()``, ``n_samples=0``.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")

    n = len(pairs)
    if n == 0:
        return CalibrationResult(ece=0.0, bins=(), n_samples=0)

    width = 1.0 / n_bins
    # Per-bin accumulators: sum of confidences and count of correct predictions.
    conf_sums = [0.0] * n_bins
    correct_counts = [0] * n_bins
    counts = [0] * n_bins

    for confidence, was_correct in pairs:
        clamped = _clamp_unit(float(confidence))
        idx = _bin_index(clamped, n_bins)
        conf_sums[idx] += clamped
        counts[idx] += 1
        if was_correct:
            correct_counts[idx] += 1

    bins: list[ReliabilityBin] = []
    ece = 0.0
    for idx in range(n_bins):
        count = counts[idx]
        if count == 0:
            continue
        mean_confidence = conf_sums[idx] / count
        accuracy = correct_counts[idx] / count
        lower = idx * width
        upper = (idx + 1) * width
        ece += (count / n) * abs(accuracy - mean_confidence)
        bins.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                mean_confidence=mean_confidence,
                accuracy=accuracy,
                count=count,
            )
        )

    return CalibrationResult(ece=ece, bins=tuple(bins), n_samples=n)
