"""Unit tests for streamforge.eval.metrics."""
from __future__ import annotations

import pytest

from streamforge.eval.metrics import (
    detection_latency,
    fpr_null,
    score_drift,
    score_schema,
)
from streamforge.eval.types import DriftLabel, FieldTruth, SchemaTruth
from streamforge.models import (
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    PIICategory,
)


# ── Builders ──────────────────────────────────────────────────────────────────
def make_field(
    path: str,
    field_type: FieldType = FieldType.STRING,
    pii: list[PIICategory] | None = None,
    required: bool = True,
) -> FieldSchema:
    return FieldSchema(
        name=path.split(".")[-1],
        path=path,
        field_type=field_type,
        required=required,
        pii_categories=pii or [],
    )


def make_truth_field(
    path: str,
    field_type: FieldType = FieldType.STRING,
    pii: tuple[PIICategory, ...] = (),
    required: bool = True,
) -> FieldTruth:
    return FieldTruth(
        path=path, field_type=field_type, required=required, pii_categories=pii
    )


def make_drift(field_path: str, drift_type: str) -> FieldDrift:
    return FieldDrift(
        field_path=field_path,
        drift_type=drift_type,
        affected_event_rate=0.5,
        tier=DriftTier.TIER_1,
        auto_correctable=False,
    )


def make_report(drifts: list[FieldDrift]) -> DriftReport:
    return DriftReport(
        stream_name="orders",
        detected_at="2026-06-18T00:00:00Z",
        schema_version="1.0.0",
        events_sampled=100,
        drifts=drifts,
        highest_tier=DriftTier.TIER_1,
        summary="test",
    )


# ── score_schema ─────────────────────────────────────────────────────────────
def test_score_schema_perfect_match():
    truth = SchemaTruth(
        stream_name="orders",
        fields=(
            make_truth_field("id", FieldType.UUID),
            make_truth_field("email", FieldType.EMAIL, pii=(PIICategory.EMAIL,)),
        ),
    )
    inferred = [
        make_field("id", FieldType.UUID),
        make_field("email", FieldType.EMAIL, pii=[PIICategory.EMAIL]),
    ]
    result = score_schema(inferred, truth)

    assert result.type_prf.tp == 2
    assert result.type_prf.fp == 0
    assert result.type_prf.fn == 0
    assert result.type_prf.precision == 1.0
    assert result.type_prf.recall == 1.0
    assert result.type_prf.f1 == 1.0
    assert result.type_accuracy == 1.0
    assert result.pii_prf.tp == 1
    assert result.pii_prf.fp == 0
    assert result.pii_prf.fn == 0
    assert result.n_truth == 2
    assert result.n_inferred == 2


def test_score_schema_partial_match_missing_and_extra():
    truth = SchemaTruth(
        stream_name="orders",
        fields=(
            make_truth_field("id", FieldType.UUID),
            make_truth_field("amount", FieldType.FLOAT),  # not inferred -> FN
        ),
    )
    inferred = [
        make_field("id", FieldType.UUID),
        make_field("ghost", FieldType.STRING),  # not in truth -> FP
    ]
    result = score_schema(inferred, truth)

    assert result.type_prf.tp == 1  # only "id" matched
    assert result.type_prf.fn == 1  # "amount" missing
    assert result.type_prf.fp == 1  # "ghost" extra
    assert result.type_prf.precision == pytest.approx(0.5)
    assert result.type_prf.recall == pytest.approx(0.5)


def test_score_schema_type_mismatch_lowers_accuracy():
    truth = SchemaTruth(
        stream_name="orders",
        fields=(
            make_truth_field("a", FieldType.INTEGER),
            make_truth_field("b", FieldType.STRING),
        ),
    )
    inferred = [
        make_field("a", FieldType.STRING),  # wrong type
        make_field("b", FieldType.STRING),  # correct type
    ]
    result = score_schema(inferred, truth)

    # both paths detected
    assert result.type_prf.tp == 2
    assert result.type_prf.f1 == 1.0
    # but only 1 of 2 has correct type
    assert result.type_accuracy == pytest.approx(0.5)


def test_score_schema_no_matches_type_accuracy_zero():
    truth = SchemaTruth(
        stream_name="orders",
        fields=(make_truth_field("a", FieldType.INTEGER),),
    )
    inferred = [make_field("b", FieldType.STRING)]
    result = score_schema(inferred, truth)

    assert result.type_prf.tp == 0
    assert result.type_accuracy == 0.0


def test_score_schema_empty_inferred():
    truth = SchemaTruth(
        stream_name="orders",
        fields=(make_truth_field("a"), make_truth_field("b")),
    )
    result = score_schema([], truth)

    assert result.type_prf.tp == 0
    assert result.type_prf.fn == 2
    assert result.type_prf.fp == 0
    assert result.type_prf.recall == 0.0
    assert result.type_accuracy == 0.0
    assert result.n_inferred == 0
    assert result.n_truth == 2


def test_score_schema_pii_pair_matching():
    # truth: email field has EMAIL pii; inferred mislabels category on email
    # and adds a spurious pii on another field.
    truth = SchemaTruth(
        stream_name="users",
        fields=(
            make_truth_field("email", FieldType.EMAIL, pii=(PIICategory.EMAIL,)),
            make_truth_field("ssn", FieldType.STRING, pii=(PIICategory.NATIONAL_ID,)),
        ),
    )
    inferred = [
        make_field("email", FieldType.EMAIL, pii=[PIICategory.EMAIL]),  # TP
        make_field("ssn", FieldType.STRING, pii=[PIICategory.PHONE]),  # wrong cat
    ]
    result = score_schema(inferred, truth)

    # (email, EMAIL) is TP. (ssn, NATIONAL_ID) missing -> FN.
    # (ssn, PHONE) extra -> FP.
    assert result.pii_prf.tp == 1
    assert result.pii_prf.fn == 1
    assert result.pii_prf.fp == 1


# ── score_drift ──────────────────────────────────────────────────────────────
def test_score_drift_perfect_match():
    expected = [
        DriftLabel("amount", "type_changed"),
        DriftLabel("status", "enum_changed"),
    ]
    report = make_report(
        [make_drift("amount", "type_changed"), make_drift("status", "enum_changed")]
    )
    prf = score_drift(report, expected)
    assert prf.tp == 2
    assert prf.fp == 0
    assert prf.fn == 0
    assert prf.f1 == 1.0


def test_score_drift_partial():
    expected = [
        DriftLabel("amount", "type_changed"),
        DriftLabel("status", "enum_changed"),
    ]
    report = make_report(
        [
            make_drift("amount", "type_changed"),  # TP
            make_drift("extra", "field_added"),  # FP
        ]
    )
    prf = score_drift(report, expected)
    assert prf.tp == 1
    assert prf.fp == 1
    assert prf.fn == 1  # status missed


def test_score_drift_none_detected():
    expected = [DriftLabel("amount", "type_changed")]
    prf = score_drift(None, expected)
    assert prf.tp == 0
    assert prf.fp == 0
    assert prf.fn == 1
    assert prf.recall == 0.0


def test_score_drift_same_path_different_type_is_not_match():
    expected = [DriftLabel("amount", "type_changed")]
    report = make_report([make_drift("amount", "presence_drop")])
    prf = score_drift(report, expected)
    assert prf.tp == 0
    assert prf.fn == 1
    assert prf.fp == 1


# ── detection_latency ────────────────────────────────────────────────────────
def test_detection_latency_first_true_positive():
    expected = [DriftLabel("amount", "type_changed")]
    timeline = [
        (50, make_report([])),  # nothing
        (100, make_report([make_drift("other", "field_added")])),  # FP only
        (150, make_report([make_drift("amount", "type_changed")])),  # first TP
        (200, make_report([make_drift("amount", "type_changed")])),
    ]
    assert detection_latency(timeline, expected) == 150


def test_detection_latency_never_detected():
    expected = [DriftLabel("amount", "type_changed")]
    timeline = [
        (50, make_report([])),
        (100, make_report([make_drift("other", "field_added")])),
        (150, None),
    ]
    assert detection_latency(timeline, expected) is None


def test_detection_latency_empty_expected():
    timeline = [(50, make_report([make_drift("amount", "type_changed")]))]
    assert detection_latency(timeline, []) is None


def test_detection_latency_handles_none_reports():
    expected = [DriftLabel("x", "presence_drop")]
    timeline = [
        (10, None),
        (20, make_report([make_drift("x", "presence_drop")])),
    ]
    assert detection_latency(timeline, expected) == 20


# ── fpr_null ─────────────────────────────────────────────────────────────────
def test_fpr_null_clean_holdout_no_false_positives():
    assert fpr_null(make_report([]), 10) == 0.0


def test_fpr_null_counts_all_drifts_as_false_positives():
    report = make_report(
        [make_drift("a", "type_changed"), make_drift("b", "presence_drop")]
    )
    assert fpr_null(report, 10) == pytest.approx(0.2)


def test_fpr_null_zero_fields_tested():
    report = make_report([make_drift("a", "type_changed")])
    assert fpr_null(report, 0) == 0.0
    assert fpr_null(report, -5) == 0.0


def test_fpr_null_none_detected():
    assert fpr_null(None, 10) == 0.0
