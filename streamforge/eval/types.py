"""Shared contract for the evaluation harness.

Every module in ``streamforge.eval`` imports its data shapes from here. These are
frozen dataclasses (immutable per coding standards) — never mutate, always
construct anew. This file is the single source of truth for the harness so the
metrics, calibration, injection, and runner modules cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from streamforge.models import FieldType, PIICategory

# ── Drift type vocabulary (must match streamforge.detector emissions) ──────────
# These are the exact ``FieldDrift.drift_type`` strings the detector produces.
# Injection labels MUST use these so detected/expected comparison is apples-to-apples.
DRIFT_TYPES: tuple[str, ...] = (
    "type_changed",
    "presence_drop",
    "presence_increase",
    "enum_changed",
    "field_added",
    "field_removed",
    "new_pii",
    "new_cluster",
    "cluster_routing_regression",
)


# ── Ground truth ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldTruth:
    """Hand-labeled truth for a single field path in a stream's schema."""

    path: str
    field_type: FieldType
    required: bool = True
    pii_categories: tuple[PIICategory, ...] = ()


@dataclass(frozen=True)
class SchemaTruth:
    """Hand-labeled ground-truth schema for one stream."""

    stream_name: str
    fields: tuple[FieldTruth, ...]

    def by_path(self) -> dict[str, FieldTruth]:
        return {f.path: f for f in self.fields}


# ── Drift injection ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DriftSpec:
    """Describes one drift to inject into a clean event batch.

    kind ∈ {"type_flip", "enum_add", "presence_drop", "field_added",
            "field_removed", "pii_add", "nesting_change"}.
    ``rate`` is the fraction of events affected (0..1). ``params`` carries
    kind-specific options (e.g. {"new_value": "BLOCKED"} for enum_add).
    """

    kind: str
    field_path: str
    rate: float = 1.0
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DriftLabel:
    """Expected drift the detector should report, given an injected DriftSpec."""

    field_path: str
    drift_type: str  # one of DRIFT_TYPES


# ── Metric results ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PRF:
    """Precision / recall / F1 with the underlying confusion counts."""

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int

    @staticmethod
    def from_counts(tp: int, fp: int, fn: int) -> PRF:
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return PRF(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn)


@dataclass(frozen=True)
class SchemaEvalResult:
    """Schema-inference accuracy vs ground truth for one stream."""

    type_prf: PRF        # per-field-path detection (did we find the field at all)
    pii_prf: PRF         # PII category detection
    type_accuracy: float  # of matched paths, fraction with correct field_type
    n_truth: int
    n_inferred: int


@dataclass(frozen=True)
class DriftEvalResult:
    """Drift-detection accuracy vs injected labels."""

    prf: PRF
    detection_latency_events: int | None  # events consumed before first true detection
    fpr_null: float | None = None          # false-positive rate on a clean holdout


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of a reliability diagram."""

    lower: float          # bin lower edge (confidence)
    upper: float          # bin upper edge (confidence)
    mean_confidence: float
    accuracy: float
    count: int


@dataclass(frozen=True)
class CalibrationResult:
    """Confidence calibration of inference (does 0.9 mean 90% correct?)."""

    ece: float                         # expected calibration error (lower is better)
    bins: tuple[ReliabilityBin, ...]
    n_samples: int
