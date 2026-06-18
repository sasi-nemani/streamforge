"""Tests for streamforge.eval.runner — the reproducible benchmark scorecard.

These run OFFLINE (no LLM key), so inference must take the deterministic
statistical path. The whole point of this suite is to lock in determinism and
the headline accuracy numbers the demo / CI depend on.
"""
from __future__ import annotations

import logging

import pytest

from streamforge.eval.runner import (
    Scorecard,
    build_inferred_schema,
    default_scenarios,
    evaluate_drift,
    infer_fields,
    load_stream_events,
    run_benchmark,
)
from streamforge.models import FieldSchema, FieldType, InferredSchema

STREAMS = ("payments", "bookings")


@pytest.fixture(autouse=True)
def _quiet_and_offline(monkeypatch):
    """Silence logs and force the offline statistical path for every test."""
    monkeypatch.setenv("STREAMFORGE_AUDIT", "0")
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _assert_unit_interval(value: float) -> None:
    assert 0.0 <= value <= 1.0


@pytest.mark.parametrize("stream", STREAMS)
def test_run_benchmark_succeeds_and_is_offline(stream):
    sc = run_benchmark(stream, seed=42)
    assert isinstance(sc, Scorecard)
    assert sc.stream == stream
    assert sc.seed == 42
    # No API key in the test env → statistical fallback.
    assert sc.inference_path == "statistical"


@pytest.mark.parametrize("stream", STREAMS)
def test_all_metrics_in_unit_interval(stream):
    sc = run_benchmark(stream, seed=42)
    for prf in (sc.schema.type_prf, sc.schema.pii_prf, sc.drift.prf):
        _assert_unit_interval(prf.precision)
        _assert_unit_interval(prf.recall)
        _assert_unit_interval(prf.f1)
    _assert_unit_interval(sc.schema.type_accuracy)
    _assert_unit_interval(sc.calibration.ece)


@pytest.mark.parametrize("stream", STREAMS)
def test_fpr_null_is_zero(stream):
    # Baseline is self-consistent (built from the clean first half), so a clean
    # holdout must produce no false-positive drift.
    sc = run_benchmark(stream, seed=42)
    assert sc.drift.fpr_null == 0.0


@pytest.mark.parametrize("stream", STREAMS)
def test_detection_latency_is_int(stream):
    sc = run_benchmark(stream, seed=42)
    assert isinstance(sc.drift.detection_latency_events, int)
    assert sc.drift.detection_latency_events > 0


@pytest.mark.parametrize("stream", STREAMS)
def test_determinism_same_seed_same_scores(stream):
    a = run_benchmark(stream, seed=42)
    b = run_benchmark(stream, seed=42)
    assert a.drift.prf.f1 == b.drift.prf.f1
    assert a.schema.type_prf.f1 == b.schema.type_prf.f1
    assert a.scenarios == b.scenarios
    assert a.drift.detection_latency_events == b.drift.detection_latency_events


@pytest.mark.parametrize("stream", STREAMS)
def test_reliable_scenarios_have_high_f1(stream):
    # presence_drop / field_added / field_removed (and type_flip) are reliable.
    sc = run_benchmark(stream, seed=42)
    high = [label for label, f1 in sc.scenarios if f1 >= 0.99]
    assert len(high) >= 3, f"expected >=3 high-F1 scenarios, got {sc.scenarios}"


@pytest.mark.parametrize("stream", STREAMS)
def test_schema_type_f1_meets_floor(stream):
    sc = run_benchmark(stream, seed=42)
    assert sc.schema.type_prf.f1 >= 0.85


@pytest.mark.parametrize("stream", STREAMS)
def test_infer_fields_returns_statistical_path(stream):
    events = load_stream_events(stream)
    assert events  # events exist on disk
    fields, path = infer_fields(stream, events)
    assert path == "statistical"
    assert isinstance(fields, list)
    assert all(isinstance(f, FieldSchema) for f in fields)
    assert fields  # non-empty


def test_load_stream_events_unknown_raises_key_error():
    with pytest.raises(KeyError):
        load_stream_events("not_a_stream")


def test_build_inferred_schema_wraps_fields():
    fields = [
        FieldSchema(
            name="amount",
            path="amount",
            field_type=FieldType.STRING,
            confidence=1.0,
            presence_rate=1.0,
            required=True,
            pii_categories=[],
        )
    ]
    schema = build_inferred_schema("payments", fields, event_count=123)
    assert isinstance(schema, InferredSchema)
    assert schema.stream_name == "payments"
    assert schema.event_count_sampled == 123
    assert list(schema.fields) == fields


def test_default_scenarios_payments_non_empty():
    scenarios = default_scenarios("payments")
    assert scenarios
    assert "field_removed:currency" in scenarios


def test_default_scenarios_unknown_stream_empty():
    assert default_scenarios("unknown_stream") == {}


@pytest.mark.parametrize("stream", STREAMS)
def test_evaluate_drift_determinism(stream):
    events = load_stream_events(stream)
    res_a, scen_a = evaluate_drift(stream, events, seed=42)
    res_b, scen_b = evaluate_drift(stream, events, seed=42)
    assert res_a.prf.f1 == res_b.prf.f1
    assert res_a.fpr_null == res_b.fpr_null
    assert scen_a == scen_b
