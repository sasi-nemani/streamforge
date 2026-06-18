"""Previously-silent failure paths now increment visible counters."""
from __future__ import annotations

import os
import tempfile

import pytest

from streamforge import metrics
from streamforge.metrics import (
    DLQ_FAILURES,
    PARSE_FAILURES,
    metrics_snapshot,
    prometheus_text,
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics._reset_for_testing()
    yield
    metrics._reset_for_testing()


def test_snapshot_exposes_failure_counters():
    snap = metrics_snapshot()
    for key in (
        "parse_failures_total",
        "dlq_route_failures_total",
        "audit_write_failures_total",
        "inference_failures_total",
    ):
        assert key in snap
        assert snap[key] == 0.0


def test_malformed_events_increment_parse_failures():
    from streamforge.sampler import load_events_resilient

    d = tempfile.mkdtemp()
    with open(os.path.join(d, "e.ndjson"), "w", encoding="utf-8") as f:
        f.write('{"a": 1}\n')           # clean
        f.write("definitely not json\n")  # unparseable -> dropped
        f.write('{"b": 2}\n')           # clean
    events, stats = load_events_resilient(d)

    assert len(events) == 2
    assert stats["skipped"] == 1
    assert PARSE_FAILURES.value == 1.0


def test_dlq_routing_failure_is_counted(monkeypatch):
    from streamforge.dlq import DLQConfig, DLQRouter

    router = DLQRouter("orders", ["broker:9092"], DLQConfig(enabled=True))

    def _boom(*_a, **_k):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(router, "_publish", _boom)
    routed = router.route([{"x": 1}, {"x": 2}], violation_type="schema_violation")

    assert routed == 0
    assert DLQ_FAILURES.value == 2.0  # both events counted as failed-to-route


def test_failure_counters_render_in_prometheus():
    PARSE_FAILURES.inc(3)
    text = prometheus_text()
    assert "parse_failures_total" in text
    assert "audit_write_failures_total" in text
