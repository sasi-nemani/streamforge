"""
Memory-efficient field statistics using streaming sketches.

Design philosophy (staff engineer notes):
  - Full events are O(event_size × window_size) = 10-50MB per topic
  - Statistical drift detection only needs:
    - Presence rate: 1 counter per field
    - Type distribution: dict of type → count
    - Enum distribution: dict of value → count (capped)
    - Numeric distribution: T-Digest or DDSketch (few KB)

  - This module implements FieldSketch: O(1KB) per field regardless of events seen.
  - 100 fields × 1KB = 100KB per topic vs 50MB = 500x reduction.

  - Trade-off: Can't replay raw events for debugging. Keep tiny sample (50 events)
    for that, not 2000.

References:
  - T-Digest: Dunning & Ertl (2019) for streaming quantiles
  - Count-Min Sketch: Cormode & Muthukrishnan (2005) for heavy hitters
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Enum cardinality cap: beyond this, we track "top-k" only
_MAX_ENUM_VALUES = 50


@dataclass
class FieldSketch:
    """
    Memory-efficient statistics for a single field.

    Stores only what's needed for drift detection:
    - Presence: count of events where field was present / total events
    - Type distribution: Counter of observed types
    - Enum values: Counter of string values (capped at _MAX_ENUM_VALUES)

    Memory: ~500 bytes to 2KB per field depending on enum cardinality.
    vs full events: 5KB × 2000 = 10MB per field's samples
    """

    total_events: int = 0
    present_count: int = 0
    type_counts: Counter = field(default_factory=Counter)
    enum_counts: Counter = field(default_factory=Counter)
    _enum_capped: bool = False

    def update(self, value: Any) -> None:
        """Update sketch with a single observed value (or None if absent)."""
        self.total_events += 1

        if value is None:
            return

        self.present_count += 1

        # Track type
        type_name = _infer_type_name(value)
        self.type_counts[type_name] += 1

        # Track enum (string values only, capped)
        if isinstance(value, str) and len(value) < 100:
            if len(self.enum_counts) < _MAX_ENUM_VALUES or value in self.enum_counts:
                self.enum_counts[value] += 1
            else:
                self._enum_capped = True

    @property
    def presence_rate(self) -> float:
        if self.total_events == 0:
            return 0.0
        return self.present_count / self.total_events

    @property
    def dominant_type(self) -> str | None:
        if not self.type_counts:
            return None
        return self.type_counts.most_common(1)[0][0]

    @property
    def type_distribution(self) -> dict[str, float]:
        """Normalized type distribution."""
        if self.present_count == 0:
            return {}
        return {t: c / self.present_count for t, c in self.type_counts.items()}

    @property
    def enum_values(self) -> list[str]:
        """Known enum values (may be incomplete if capped)."""
        return list(self.enum_counts.keys())

    def memory_bytes(self) -> int:
        """Estimate memory usage in bytes."""
        base = 64  # object overhead + counters
        type_mem = len(self.type_counts) * 50  # ~50 bytes per type entry
        enum_mem = sum(len(k) + 16 for k in self.enum_counts)  # string + count
        return base + type_mem + enum_mem


@dataclass
class SchemaSketch:
    """
    Streaming statistics for an entire schema (all fields).

    Memory: O(num_fields × 1KB) instead of O(num_events × event_size).
    For 100 fields: ~100KB vs 50MB = 500x reduction.

    Also keeps a tiny sample (50 events) for debugging / manual inspection.
    """

    fields: dict[str, FieldSketch] = field(default_factory=dict)
    _debug_sample: list[dict] = field(default_factory=list)
    _debug_sample_max: int = 50

    def update(self, event: dict) -> None:
        """Update all field sketches from a single event."""
        # Flatten nested event to dot-paths
        flat = _flatten_event(event)

        # Update existing fields
        seen_paths = set()
        for path, value in flat.items():
            if path not in self.fields:
                self.fields[path] = FieldSketch()
            self.fields[path].update(value)
            seen_paths.add(path)

        # Mark absent fields
        for path, sketch in self.fields.items():
            if path not in seen_paths:
                sketch.update(None)

        # Keep tiny debug sample (reservoir sampling)
        if len(self._debug_sample) < self._debug_sample_max:
            self._debug_sample.append(event)
        else:
            import random
            # Total events seen across all fields (use any field)
            n = next(iter(self.fields.values())).total_events if self.fields else 1
            j = random.randint(0, n - 1)
            if j < self._debug_sample_max:
                self._debug_sample[j] = event

    def total_events(self) -> int:
        """Total events processed."""
        if not self.fields:
            return 0
        return next(iter(self.fields.values())).total_events

    def memory_bytes(self) -> int:
        """Estimate total memory usage."""
        field_mem = sum(s.memory_bytes() for s in self.fields.values())
        sample_mem = len(self._debug_sample) * 2000  # ~2KB avg event
        return field_mem + sample_mem


def _infer_type_name(value: Any) -> str:
    """Infer StreamForge type name from Python value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        # Could add UUID/email/timestamp detection here
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _flatten_event(event: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict to dot-path keys."""
    result = {}
    for key, value in event.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_event(value, path))
        else:
            result[path] = value
    return result


# ---------------------------------------------------------------------------
# Integration with existing drift detection
# ---------------------------------------------------------------------------

def sketch_to_presence_rates(sketch: SchemaSketch) -> dict[str, float]:
    """Convert sketch to presence rate dict (compatible with sampler output)."""
    return {path: s.presence_rate for path, s in sketch.fields.items()}


def sketch_to_field_values(sketch: SchemaSketch, n: int = 50) -> dict[str, list[Any]]:
    """
    Extract sample values from debug sample for each field.

    This is less accurate than full window but sufficient for:
    - Type inference fallback
    - PII detection (pattern matching on samples)
    - Enum value discovery
    """
    result: dict[str, list[Any]] = {path: [] for path in sketch.fields}

    for event in sketch._debug_sample:
        flat = _flatten_event(event)
        for path, value in flat.items():
            if path in result and value is not None and len(result[path]) < n:
                result[path].append(value)

    return result
