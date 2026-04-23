"""
Statistical Confidence Module.

Calculates confidence intervals and coverage guarantees for multi-schema detection.
Uses Wilson score interval for proportion confidence intervals.

Example:
    >>> from streamforge.confidence import wilson_score_interval, calculate_type_confidence
    >>> lower, upper = wilson_score_interval(50, 100)  # 50 successes in 100 trials
    >>> print(f"95% CI: ({lower:.2f}, {upper:.2f})")  # ~(0.40, 0.60)
"""

from __future__ import annotations

import math
from typing import Any

from .models import TypeConfidence

# Z-score for 95% confidence
Z_95 = 1.96


def wilson_score_interval(
    successes: int,
    total: int,
    z: float = Z_95,
) -> tuple[float, float]:
    """
    Calculate Wilson score interval for a proportion.

    More accurate than normal approximation, especially for small samples.
    Reference: https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval

    Args:
        successes: Number of successes (e.g., events of this type)
        total: Total trials (e.g., total events sampled)
        z: Z-score for confidence level (1.96 for 95%)

    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    if total == 0:
        return (0.0, 0.0)

    p_hat = successes / total
    z_sq = z * z

    denominator = 1 + z_sq / total
    center = p_hat + z_sq / (2 * total)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z_sq / (4 * total)) / total)

    lower = (center - margin) / denominator
    upper = (center + margin) / denominator

    return (max(0.0, lower), min(1.0, upper))


def calculate_type_confidence(
    type_counts: dict[str, int],
    total_sampled: int,
    total_population: int | None = None,
    min_valid_samples: int = 30,
    schema_confidence_map: dict[str, float] | None = None,
) -> list[TypeConfidence]:
    """
    Calculate confidence metrics for each event type.

    Args:
        type_counts: Dict mapping type_value to sample count
        total_sampled: Total number of events sampled
        total_population: Estimated population size (optional)
        min_valid_samples: Minimum samples for statistical validity
        schema_confidence_map: Optional map of type -> inference confidence

    Returns:
        List of TypeConfidence objects
    """
    if not type_counts or total_sampled == 0:
        return []

    result: list[TypeConfidence] = []
    schema_conf = schema_confidence_map or {}

    for type_value, count in type_counts.items():
        frequency = count / total_sampled
        lower, upper = wilson_score_interval(count, total_sampled)

        # Estimate population count if total_population known
        pop_estimate = None
        if total_population is not None:
            pop_estimate = int(frequency * total_population)

        # Schema confidence: use provided or estimate from sample size
        s_conf = schema_conf.get(type_value)
        if s_conf is None:
            # Heuristic: confidence scales with log of sample size
            # 100+ samples -> high confidence, <10 -> low
            s_conf = min(0.99, 0.5 + 0.1 * math.log10(max(count, 1)))

        result.append(
            TypeConfidence(
                type_value=type_value,
                sample_count=count,
                population_estimate=pop_estimate,
                frequency=frequency,
                confidence_lower=lower,
                confidence_upper=upper,
                schema_confidence=s_conf,
                statistically_valid=count >= min_valid_samples,
            )
        )

    return result


def calculate_overall_confidence(
    type_confidences: list[TypeConfidence],
) -> float:
    """
    Calculate overall confidence weighted by type frequency.

    Types with more samples contribute more to overall confidence.
    """
    if not type_confidences:
        return 0.0

    weighted_sum = sum(tc.frequency * tc.schema_confidence for tc in type_confidences)
    total_frequency = sum(tc.frequency for tc in type_confidences)

    if total_frequency == 0:
        return 0.0

    return weighted_sum / total_frequency


def generate_coverage_guarantee(
    total_sampled: int,
    min_samples_per_type: int = 3,
    confidence_level: float = 0.95,
) -> str:
    """
    Generate a human-readable coverage guarantee statement.

    Calculates the minimum frequency a type must have to be detected
    with the given confidence level.

    Args:
        total_sampled: Number of events sampled
        min_samples_per_type: Minimum samples needed to detect a type
        confidence_level: Statistical confidence level (e.g., 0.95)

    Returns:
        Human-readable guarantee statement
    """
    if total_sampled == 0:
        return "No events sampled - no coverage guarantee"

    # Probability of missing a type with frequency f:
    # P(miss) = (1-f)^n where n = total_sampled
    # We want P(miss) < (1 - confidence_level)
    # (1-f)^n < 0.05
    # n * ln(1-f) < ln(0.05)
    # For small f: ln(1-f) ≈ -f
    # -n*f < ln(0.05)
    # f > -ln(0.05)/n = ln(20)/n ≈ 3/n

    # More precise: solve for f such that we expect >= min_samples_per_type
    # Expected count = f * n >= min_samples_per_type
    # f >= min_samples_per_type / n

    min_frequency = min_samples_per_type / total_sampled
    percentage = min_frequency * 100

    conf_pct = int(confidence_level * 100)

    if percentage < 0.01:
        return f"{conf_pct}% confident all types >0.01% are captured"
    elif percentage < 0.1:
        return f"{conf_pct}% confident all types >0.{int(percentage*10)}% are captured"
    elif percentage < 1:
        return f"{conf_pct}% confident all types >{percentage:.1f}% are captured"
    else:
        return f"{conf_pct}% confident all types >{percentage:.0f}% are captured"
