"""
Multi-Schema Confidence Orchestrator.

Main entry point for multi-schema detection with confidence scoring.
Coordinates discriminator detection, stratified sampling, and confidence calculation.

Example:
    >>> from streamforge.multi_schema_confidence import analyze_multi_schema
    >>> events = [{"type": "payment", ...}, {"type": "refund", ...}, ...]
    >>> result = analyze_multi_schema(events)
    >>> print(f"Detected {result.types_detected} schemas with {result.overall_confidence:.0%} confidence")
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, TextIO

from .confidence import (
    calculate_overall_confidence,
    calculate_type_confidence,
    generate_coverage_guarantee,
)
from .discriminator import detect_discriminator
from .distribution import calculate_distribution
from .models import (
    DiscriminatorInfo,
    DiscriminatorMethod,
    MultiSchemaConfidence,
    SamplingReport,
)
from .multi_schema_audit import emit_audit
from .stratified_sampler import stratified_sample

logger = logging.getLogger(__name__)


def analyze_multi_schema(
    events: list[dict[str, Any]],
    discriminator: str | None = None,
    candidates: list[str] | None = None,
    sample_size: int = 1000,
    min_per_type: int = 10,
    min_cardinality: int = 2,
    max_cardinality: int = 100,
    audit_stream: TextIO | None = None,
    stream_name: str = "unknown",
) -> MultiSchemaConfidence:
    """
    Analyze events for multi-schema patterns with confidence scoring.

    This is the main entry point for the multi-schema confidence system.
    It coordinates:
    1. Discriminator detection (or validation)
    2. Stratified sampling
    3. Distribution calculation
    4. Confidence interval calculation

    Args:
        events: List of event dictionaries
        discriminator: Explicit discriminator field (optional)
        candidates: Candidate discriminator fields (optional)
        sample_size: Target sample size
        min_per_type: Minimum samples per type (for stratified sampling)
        min_cardinality: Minimum types for valid discriminator
        max_cardinality: Maximum types for valid discriminator
        audit_stream: Optional stream for audit events
        stream_name: Name of stream for telemetry

    Returns:
        MultiSchemaConfidence with full analysis results
    """
    start_time = time.perf_counter()
    detection_time_ms: float | None = None
    inference_time_ms: float | None = None
    warnings: list[str] = []

    # Handle empty events
    if not events:
        return MultiSchemaConfidence(
            discriminator=DiscriminatorInfo(
                field_path="",
                method=DiscriminatorMethod.STRUCTURAL,
                cardinality=0,
                coverage=0.0,
                entropy=0.0,
            ),
            types_detected=0,
            distribution=[],
            per_type_confidence=[],
            overall_confidence=0.0,
            coverage_guarantee="No events to analyze",
            sampling=SamplingReport(
                total_population=0,
                total_sampled=0,
            ),
            warnings=["empty event list"],
            detection_time_ms=0.0,
            inference_time_ms=0.0,
        )

    # Step 1: Detect discriminator
    detect_start = time.perf_counter()
    disc_info = detect_discriminator(
        events,
        explicit_field=discriminator,
        candidates=candidates,
        min_cardinality=min_cardinality,
        max_cardinality=max_cardinality,
        audit_stream=audit_stream,
        stream_name=stream_name,
    )
    detection_time_ms = (time.perf_counter() - detect_start) * 1000

    # Fallback to structural fingerprint if no discriminator found
    if disc_info is None:
        disc_info = _create_structural_discriminator(events)
        warnings.append("No discriminator field found - using structural fingerprint")

    # Step 2: Stratified sampling
    inference_start = time.perf_counter()

    if len(events) <= sample_size:
        # Use all events if under sample size
        grouped = _group_by_field(events, disc_info.field_path)
        sampling_report = SamplingReport(
            total_population=len(events),
            total_sampled=len(events),
            sampling_rate=1.0,
            stratified=False,
            sampling_method="exhaustive",
        )
    else:
        grouped, sampling_report = stratified_sample(
            events,
            discriminator_field=disc_info.field_path,
            total_size=sample_size,
            min_per_type=min_per_type,
            audit_stream=audit_stream,
            stream_name=stream_name,
        )

    # Step 3: Calculate distribution
    all_sampled = []
    for type_events in grouped.values():
        all_sampled.extend(type_events)

    distribution = calculate_distribution(
        all_sampled,
        discriminator_field=disc_info.field_path,
    )

    # Step 4: Calculate confidence
    type_counts = {d.type_value: d.count for d in distribution}
    per_type_conf = calculate_type_confidence(
        type_counts=type_counts,
        total_sampled=len(all_sampled),
        total_population=len(events),
    )

    overall_conf = calculate_overall_confidence(per_type_conf)
    coverage_msg = generate_coverage_guarantee(
        total_sampled=len(all_sampled),
        min_samples_per_type=min_per_type,
    )

    inference_time_ms = (time.perf_counter() - inference_start) * 1000

    # Add warnings for types below threshold
    for tc in per_type_conf:
        if not tc.statistically_valid:
            warnings.append(
                f"{tc.type_value}: {tc.sample_count} samples "
                f"(need 30+ for statistical validity)"
            )

    # Emit final audit event
    emit_audit(
        audit_stream,
        stream_name,
        "multi_schema_analysis",
        start_time,
        len(events),
        len(grouped),
        details={
            "types_detected": len(grouped),
            "overall_confidence": overall_conf,
            "discriminator": disc_info.field_path,
        },
    )

    return MultiSchemaConfidence(
        discriminator=disc_info,
        types_detected=len(grouped),
        distribution=distribution,
        per_type_confidence=per_type_conf,
        overall_confidence=overall_conf,
        coverage_guarantee=coverage_msg,
        sampling=sampling_report,
        warnings=warnings,
        detection_time_ms=detection_time_ms,
        inference_time_ms=inference_time_ms,
    )


def _group_by_field(
    events: list[dict[str, Any]],
    field_path: str,
) -> dict[str, list[dict[str, Any]]]:
    """Group events by field value."""
    from .discriminator import get_nested_value

    grouped: dict[str, list[dict[str, Any]]] = {}

    for event in events:
        value = get_nested_value(event, field_path)
        if value is None:
            key = "_null"
        else:
            key = str(value) if not isinstance(value, str) else value

        if key not in grouped:
            grouped[key] = []
        grouped[key].append(event)

    return grouped


def _create_structural_discriminator(
    events: list[dict[str, Any]],
) -> DiscriminatorInfo:
    """Create a structural fingerprint-based discriminator."""
    # Count unique structural fingerprints
    fingerprints: set[str] = set()

    for event in events:
        fp = _structural_fingerprint(event)
        fingerprints.add(fp)

    return DiscriminatorInfo(
        field_path="_structural_fingerprint",
        method=DiscriminatorMethod.STRUCTURAL,
        cardinality=len(fingerprints),
        coverage=1.0,  # All events have a structure
        entropy=0.0,   # Not applicable for structural
    )


def _structural_fingerprint(event: dict[str, Any]) -> str:
    """
    Generate fingerprint from event structure (keys + value types).

    Includes value types to differentiate schemas with same keys but different types.
    """
    sig_parts = []
    for k in sorted(event.keys()):
        v = event.get(k)
        type_name = type(v).__name__
        sig_parts.append(f"{k}:{type_name}")
    sig = "|".join(sig_parts)
    return hashlib.sha256(sig.encode()).hexdigest()[:16]
