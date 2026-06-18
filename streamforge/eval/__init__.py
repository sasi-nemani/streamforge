"""StreamForge evaluation harness.

Makes the system *measurable*: scores schema inference and drift detection
against hand-labeled ground truth, with calibration of reported confidence.

Public surface:
    - types:        frozen dataclasses shared across the harness (the contract)
    - benchmark:    load ground-truth schema/drift labels from eval/benchmarks/
    - inject:       deterministic drift injector + expected-label generator
    - metrics:      precision/recall/F1 for inference and drift, detection latency
    - calibration:  expected calibration error (ECE) + reliability bins
    - runner:       wires inference + detection + metrics into a scorecard
"""
from streamforge.eval.types import (
    PRF,
    CalibrationResult,
    DriftEvalResult,
    DriftLabel,
    DriftSpec,
    FieldTruth,
    ReliabilityBin,
    SchemaEvalResult,
    SchemaTruth,
)

__all__ = [
    "CalibrationResult",
    "DriftEvalResult",
    "DriftLabel",
    "DriftSpec",
    "FieldTruth",
    "PRF",
    "ReliabilityBin",
    "SchemaEvalResult",
    "SchemaTruth",
]
