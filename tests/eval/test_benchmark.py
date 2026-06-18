"""Unit tests for streamforge.eval.benchmark (ground-truth loading + validation)."""
from __future__ import annotations

import pytest

from streamforge.eval import benchmark
from streamforge.eval.types import SchemaTruth
from streamforge.models import FieldType, PIICategory


def test_benchmarks_dir_is_a_path():
    d = benchmark.benchmarks_dir()
    assert d.name == "benchmarks"
    assert d.is_dir()


def test_available_benchmarks_includes_payments_and_bookings():
    names = benchmark.available_benchmarks()
    assert "payments" in names
    assert "bookings" in names
    # Sorted, filename-stem semantics.
    assert names == sorted(names)


def test_load_truth_payments_shape_and_labels():
    truth = benchmark.load_truth("payments")
    assert isinstance(truth, SchemaTruth)
    assert truth.stream_name == "payments"
    # 14 hand-labeled fields in eval/benchmarks/payments.yaml.
    assert len(truth.fields) == 14

    by_path = truth.by_path()
    # Type labels.
    assert by_path["event_id"].field_type == FieldType.UUID
    assert by_path["timestamp"].field_type == FieldType.TIMESTAMP_EPOCH_MS
    assert by_path["amount"].field_type == FieldType.STRING
    assert by_path["user.email"].field_type == FieldType.EMAIL

    # PII labels.
    assert by_path["user.email"].pii_categories == (PIICategory.EMAIL,)
    assert by_path["user.name"].pii_categories == (PIICategory.NAME,)
    assert by_path["metadata.ip_address"].pii_categories == (PIICategory.IP_ADDRESS,)
    # Non-PII field carries no categories.
    assert by_path["currency"].pii_categories == ()

    # required flag respected.
    assert by_path["event_id"].required is True
    assert by_path["metadata.region"].required is False


def test_load_truth_bookings_loads():
    truth = benchmark.load_truth("bookings")
    assert truth.stream_name == "bookings"
    assert len(truth.fields) == 17
    by_path = truth.by_path()
    assert by_path["passengers[].date_of_birth"].field_type == FieldType.DATE
    assert by_path["passengers[].passport_number"].pii_categories == (
        PIICategory.PASSPORT,
    )


def test_load_truth_missing_stream_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        benchmark.load_truth("does_not_exist")


def test_parse_field_rejects_bad_field_type():
    with pytest.raises(ValueError):
        benchmark._parse_field({"path": "x", "field_type": "NONSENSE"}, "x")


def test_parse_field_rejects_bad_pii_category():
    with pytest.raises(ValueError):
        benchmark._parse_field(
            {"path": "x", "field_type": "string", "pii": ["NOT_A_PII"]}, "x"
        )


def test_parse_field_missing_required_keys_raises():
    with pytest.raises(ValueError):
        benchmark._parse_field({"path": "x"}, "x")


def test_parse_field_happy_path():
    ft = benchmark._parse_field(
        {"path": "user.email", "field_type": "email", "pii": ["email"]}, "payments"
    )
    assert ft.path == "user.email"
    assert ft.field_type == FieldType.EMAIL
    assert ft.pii_categories == (PIICategory.EMAIL,)
    assert ft.required is True
