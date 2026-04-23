"""
Discriminator Detection Module.

Detects the field that distinguishes event types in a mixed stream.
Uses entropy analysis to rank candidate fields.

Example:
    >>> from streamforge.discriminator import detect_discriminator
    >>> events = [{"type": "payment", ...}, {"type": "refund", ...}]
    >>> info = detect_discriminator(events)
    >>> info.field_path  # "type"
    >>> info.cardinality  # 2
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from typing import Any, TextIO

from .multi_schema_audit import emit_audit
from .models import DiscriminatorInfo, DiscriminatorMethod

logger = logging.getLogger(__name__)

# Default candidate fields (ordered by priority)
DEFAULT_CANDIDATES = [
    "type",
    "event_type",
    "eventType",
    "kind",
    "action",
    "schema",
    "_type",
    "record_type",
    "msg_type",
]


def calculate_entropy(values: list[Any]) -> float:
    """
    Calculate Shannon entropy of a value distribution.

    Higher entropy = more uniform distribution = better discriminator.
    """
    if not values:
        return 0.0

    total = len(values)
    counts = Counter(values)
    entropy = 0.0

    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    return entropy


def get_nested_value(obj: dict, path: str) -> Any:
    """Get value from nested dict using dot notation."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def detect_discriminator(
    events: list[dict[str, Any]],
    explicit_field: str | None = None,
    candidates: list[str] | None = None,
    min_cardinality: int = 2,
    max_cardinality: int = 100,
    min_coverage: float = 0.8,
    audit_stream: TextIO | None = None,
    stream_name: str = "unknown",
) -> DiscriminatorInfo | None:
    """
    Detect the discriminator field in a collection of events.

    Args:
        events: List of event dictionaries
        explicit_field: If provided, use this field (skip auto-detection)
        candidates: List of candidate field paths to evaluate
        min_cardinality: Minimum distinct values required
        max_cardinality: Maximum distinct values allowed
        min_coverage: Minimum fraction of events with field present
        audit_stream: Optional stream for audit event logging
        stream_name: Name of the stream for telemetry

    Returns:
        DiscriminatorInfo if found, None otherwise
    """
    start_time = time.perf_counter()
    audit_details: dict[str, Any] = {}

    try:
        if not events:
            emit_audit(
                audit_stream,
                stream_name,
                "discriminator_detection",
                start_time,
                len(events),
                0,
                success=True,
                details={"result": "empty_events"},
            )
            return None

        candidates = candidates or DEFAULT_CANDIDATES
        audit_details["candidates_evaluated"] = candidates

        # If explicit field provided, validate and return
        if explicit_field:
            info = _evaluate_field(events, explicit_field)
            if info:
                info.method = DiscriminatorMethod.EXPLICIT
                info.candidates_evaluated = [explicit_field]
                emit_audit(
                    audit_stream,
                    stream_name,
                    "discriminator_detection",
                    start_time,
                    len(events),
                    1,
                    details={"field": explicit_field, "method": "explicit"},
                )
                return info
            return None

        # Auto-detect: evaluate each candidate
        best_field: DiscriminatorInfo | None = None
        best_score = -1.0

        for candidate in candidates:
            info = _evaluate_field(events, candidate)
            if not info:
                continue

            # Check constraints
            if info.cardinality < min_cardinality:
                continue
            if info.cardinality > max_cardinality:
                continue
            if info.coverage < min_coverage:
                continue

            # Score: entropy normalized by log2(cardinality)
            max_entropy = math.log2(info.cardinality) if info.cardinality > 1 else 1.0
            score = info.entropy / max_entropy if max_entropy > 0 else 0.0

            # Prefer higher coverage
            score *= info.coverage

            if score > best_score:
                best_score = score
                best_field = info
                best_field.candidates_evaluated = candidates

        if best_field:
            best_field.method = DiscriminatorMethod.AUTO_DETECTED
            emit_audit(
                audit_stream,
                stream_name,
                "discriminator_detection",
                start_time,
                len(events),
                1,
                details={
                    "field": best_field.field_path,
                    "cardinality": best_field.cardinality,
                    "entropy": best_field.entropy,
                    "method": "auto_detected",
                },
            )
        else:
            emit_audit(
                audit_stream,
                stream_name,
                "discriminator_detection",
                start_time,
                len(events),
                0,
                details={"result": "no_suitable_discriminator"},
            )

        return best_field

    except Exception as e:
        logger.exception("Discriminator detection failed")
        emit_audit(
            audit_stream,
            stream_name,
            "discriminator_detection",
            start_time,
            len(events) if isinstance(events, list) else 0,
            0,
            success=False,
            error_message=str(e),
        )
        raise


def _evaluate_field(events: list[dict], field_path: str) -> DiscriminatorInfo | None:
    """Evaluate a single field as a potential discriminator."""
    values = []
    present_count = 0

    for event in events:
        value = get_nested_value(event, field_path)
        if value is not None:
            present_count += 1
            # Convert to string for consistent comparison
            values.append(str(value) if not isinstance(value, str) else value)

    if not values:
        return None

    coverage = present_count / len(events)
    unique_values = set(values)
    cardinality = len(unique_values)
    entropy = calculate_entropy(values)

    return DiscriminatorInfo(
        field_path=field_path,
        method=DiscriminatorMethod.AUTO_DETECTED,
        cardinality=cardinality,
        coverage=coverage,
        entropy=entropy,
        candidates_evaluated=[],
    )
