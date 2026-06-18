"""Scoring metrics for the StreamForge evaluation harness.

Pure, deterministic functions that compare inferred schema / detected drift
against hand-labeled ground truth. All data shapes come from the frozen
contract in :mod:`streamforge.eval.types`; domain inputs come from
:mod:`streamforge.models`. Nothing here mutates its inputs.
"""
from __future__ import annotations

from streamforge.eval.types import (
    PRF,
    DriftLabel,
    SchemaEvalResult,
    SchemaTruth,
)
from streamforge.models import DriftReport, FieldSchema


def score_schema(
    inferred_fields: list[FieldSchema], truth: SchemaTruth
) -> SchemaEvalResult:
    """Score inferred schema fields against ground truth.

    - ``type_prf``: per-path detection. TP = truth path also inferred,
      FN = truth path missing from inferred, FP = inferred path not in truth.
    - ``type_accuracy``: of paths present in both, fraction with matching
      ``field_type``. 0.0 if there are no matched paths.
    - ``pii_prf``: over (path, pii_category) pairs.
    """
    truth_by_path = truth.by_path()
    truth_paths = set(truth_by_path)
    inferred_by_path = {f.path: f for f in inferred_fields}
    inferred_paths = set(inferred_by_path)

    matched_paths = truth_paths & inferred_paths

    # ── Per-path detection PRF ──
    type_tp = len(matched_paths)
    type_fn = len(truth_paths - inferred_paths)
    type_fp = len(inferred_paths - truth_paths)
    type_prf = PRF.from_counts(type_tp, type_fp, type_fn)

    # ── Type accuracy over matched paths ──
    if matched_paths:
        correct = sum(
            1
            for path in matched_paths
            if inferred_by_path[path].field_type == truth_by_path[path].field_type
        )
        type_accuracy = correct / len(matched_paths)
    else:
        type_accuracy = 0.0

    # ── PII (path, category) pair PRF ──
    truth_pii: set[tuple[str, object]] = {
        (t.path, cat) for t in truth.fields for cat in t.pii_categories
    }
    inferred_pii: set[tuple[str, object]] = {
        (f.path, cat) for f in inferred_fields for cat in f.pii_categories
    }
    pii_tp = len(truth_pii & inferred_pii)
    pii_fn = len(truth_pii - inferred_pii)
    pii_fp = len(inferred_pii - truth_pii)
    pii_prf = PRF.from_counts(pii_tp, pii_fp, pii_fn)

    return SchemaEvalResult(
        type_prf=type_prf,
        pii_prf=pii_prf,
        type_accuracy=type_accuracy,
        n_truth=len(truth.fields),
        n_inferred=len(inferred_fields),
    )


def _drift_pairs(detected: DriftReport | None) -> set[tuple[str, str]]:
    """Set of (field_path, drift_type) pairs in a detected report (None -> empty)."""
    if detected is None:
        return set()
    return {(d.field_path, d.drift_type) for d in detected.drifts}


def _expected_pairs(expected: list[DriftLabel]) -> set[tuple[str, str]]:
    return {(e.field_path, e.drift_type) for e in expected}


def score_drift(detected: DriftReport | None, expected: list[DriftLabel]) -> PRF:
    """Compare detected drift against expected labels on (field_path, drift_type).

    TP = expected ∩ detected, FN = expected - detected, FP = detected - expected.
    """
    detected_pairs = _drift_pairs(detected)
    expected_pairs = _expected_pairs(expected)

    tp = len(expected_pairs & detected_pairs)
    fn = len(expected_pairs - detected_pairs)
    fp = len(detected_pairs - expected_pairs)
    return PRF.from_counts(tp, fp, fn)


def detection_latency(
    timeline: list[tuple[int, DriftReport | None]], expected: list[DriftLabel]
) -> int | None:
    """Events consumed before the first true-positive detection.

    ``timeline`` is ordered ``(events_consumed, report)``. Returns the
    ``events_consumed`` of the first report that contains at least one
    expected (field_path, drift_type) pair. None if never detected.
    """
    expected_pairs = _expected_pairs(expected)
    if not expected_pairs:
        return None
    for events_consumed, report in timeline:
        if _drift_pairs(report) & expected_pairs:
            return events_consumed
    return None


def fpr_null(detected: DriftReport | None, n_fields_tested: int) -> float:
    """False-positive rate on a clean (no-injected-drift) holdout.

    Every reported drift is a false positive. Returns
    ``len(detected.drifts) / n_fields_tested``. 0.0 if ``n_fields_tested <= 0``
    or ``detected`` is None.
    """
    if n_fields_tested <= 0:
        return 0.0
    if detected is None:
        return 0.0
    return len(detected.drifts) / n_fields_tested
