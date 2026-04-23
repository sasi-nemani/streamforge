"""
Stratified Sampling Module.

Provides sampling strategies that guarantee representation of rare event types.
Uses reservoir sampling within each stratum to maintain memory efficiency.

Example:
    >>> from streamforge.stratified_sampler import stratified_sample
    >>> events = [{"type": "common", ...}] * 9900 + [{"type": "rare", ...}] * 100
    >>> grouped, report = stratified_sample(events, "type", total_size=1000, min_per_type=10)
    >>> len(grouped["rare"])  # >= 10 (guaranteed)
"""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from typing import Any, TextIO

from .multi_schema_audit import emit_audit
from .discriminator import get_nested_value
from .models import SamplingReport

logger = logging.getLogger(__name__)


def uniform_sample(
    events: list[dict[str, Any]],
    size: int,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Simple uniform random sampling (reservoir sampling).

    This is the baseline - may miss rare types entirely.
    """
    if size >= len(events):
        return events.copy()

    rng = random.Random(seed)
    reservoir = events[:size]

    for i in range(size, len(events)):
        j = rng.randint(0, i)
        if j < size:
            reservoir[j] = events[i]

    return reservoir


def stratified_sample(
    events: list[dict[str, Any]],
    discriminator_field: str,
    total_size: int = 1000,
    min_per_type: int = 5,
    seed: int | None = None,
    audit_stream: TextIO | None = None,
    stream_name: str = "unknown",
) -> tuple[dict[str, list[dict[str, Any]]], SamplingReport]:
    """
    Stratified sampling with minimum representation per type.

    Guarantees that each event type gets at least min_per_type samples,
    with remaining budget allocated proportionally to type frequency.

    Args:
        events: List of event dictionaries
        discriminator_field: Field path to group by
        total_size: Total number of samples to return
        min_per_type: Minimum samples per event type
        seed: Random seed for reproducibility
        audit_stream: Optional stream for audit logging
        stream_name: Name of stream for telemetry

    Returns:
        Tuple of (grouped_samples, sampling_report)
    """
    start_time = time.perf_counter()
    rng = random.Random(seed)

    # Group events by discriminator value
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded = 0

    for event in events:
        value = get_nested_value(event, discriminator_field)
        if value is None:
            excluded += 1
            continue
        key = str(value) if not isinstance(value, str) else value
        groups[key].append(event)

    if not groups:
        report = SamplingReport(
            total_population=len(events),
            total_sampled=0,
            stratified=True,
            min_per_type=min_per_type,
            sampling_method="stratified",
        )
        emit_audit(
            audit_stream,
            stream_name,
            "stratified_sampling",
            start_time,
            len(events),
            0,
            details={"excluded": excluded, "types": 0},
        )
        return {}, report

    num_types = len(groups)
    types_below_minimum: list[str] = []

    # Calculate allocation
    # First, allocate minimum to each type
    min_total = num_types * min_per_type
    remaining_budget = max(0, total_size - min_total)

    # Calculate proportional allocation for remaining budget
    total_events = sum(len(g) for g in groups.values())
    allocations: dict[str, int] = {}

    for type_name, type_events in groups.items():
        base = min(min_per_type, len(type_events))
        proportion = len(type_events) / total_events if total_events > 0 else 0
        extra = int(remaining_budget * proportion)
        allocations[type_name] = min(base + extra, len(type_events))

        if len(type_events) < min_per_type:
            types_below_minimum.append(type_name)

    # Sample from each group
    result: dict[str, list[dict[str, Any]]] = {}
    total_sampled = 0

    for type_name, type_events in groups.items():
        n = allocations[type_name]
        if n >= len(type_events):
            result[type_name] = type_events.copy()
        else:
            # Reservoir sample within this stratum
            result[type_name] = _reservoir_sample(type_events, n, rng)
        total_sampled += len(result[type_name])

    # Build report
    sampling_rate = total_sampled / len(events) if events else None
    report = SamplingReport(
        total_population=len(events),
        total_sampled=total_sampled,
        sampling_rate=sampling_rate,
        stratified=True,
        min_per_type=min_per_type,
        types_below_minimum=types_below_minimum,
        sampling_method="stratified",
    )

    emit_audit(
        audit_stream,
        stream_name,
        "stratified_sampling",
        start_time,
        len(events),
        total_sampled,
        details={
            "types": num_types,
            "excluded": excluded,
            "types_below_minimum": types_below_minimum,
        },
    )

    return result, report


def _reservoir_sample(
    events: list[dict[str, Any]],
    size: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Reservoir sampling with provided RNG."""
    if size >= len(events):
        return events.copy()

    reservoir = events[:size].copy()

    for i in range(size, len(events)):
        j = rng.randint(0, i)
        if j < size:
            reservoir[j] = events[i]

    return reservoir
