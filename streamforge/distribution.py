"""
Distribution Report Module.

Generates distribution reports showing event type frequencies.

Example:
    >>> from streamforge.distribution import calculate_distribution
    >>> events = [{"type": "payment"}, {"type": "payment"}, {"type": "refund"}]
    >>> dist = calculate_distribution(events, "type")
    >>> print(dist[0].type_value, dist[0].percentage)  # "payment", 66.67
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .discriminator import get_nested_value
from .models import TypeDistribution


def calculate_distribution(
    events: list[dict[str, Any]],
    discriminator_field: str,
    min_samples_warning: int = 30,
) -> list[TypeDistribution]:
    """
    Calculate distribution of event types.

    Args:
        events: List of event dictionaries
        discriminator_field: Field path to group by
        min_samples_warning: Threshold for "insufficient samples" warning

    Returns:
        List of TypeDistribution sorted by frequency descending
    """
    if not events:
        return []

    # Count types
    type_counts: Counter[str] = Counter()
    excluded = 0

    for event in events:
        value = get_nested_value(event, discriminator_field)
        if value is None:
            excluded += 1
            continue
        key = str(value) if not isinstance(value, str) else value
        type_counts[key] += 1

    total = sum(type_counts.values())
    if total == 0:
        return []

    # Build distribution
    result: list[TypeDistribution] = []

    for type_value, count in type_counts.most_common():
        percentage = (count / total) * 100

        warning = None
        if count < min_samples_warning:
            warning = f"insufficient samples ({count} < {min_samples_warning})"

        result.append(
            TypeDistribution(
                type_value=type_value,
                count=count,
                percentage=round(percentage, 2),
                sample_count=count,
                warning=warning,
            )
        )

    return result


def format_distribution_report(
    distribution: list[TypeDistribution],
    max_types: int = 10,
) -> str:
    """
    Format distribution as a human-readable report.

    Args:
        distribution: List of TypeDistribution
        max_types: Maximum types to show before truncating

    Returns:
        Formatted string report
    """
    if not distribution:
        return "No types detected"

    lines = []
    for i, d in enumerate(distribution):
        if i >= max_types:
            remaining = len(distribution) - max_types
            lines.append(f"  ... and {remaining} more types")
            break

        line = f"  {d.type_value}: {d.percentage:.1f}% ({d.count} samples)"
        if d.warning:
            line += f" ⚠️ {d.warning}"
        lines.append(line)

    return "\n".join(lines)
