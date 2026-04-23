"""
Tests for P1-A (multi-schema drift detection) and P1-B (rolling EventWindow).

All tests are purely in-memory — no API calls, no filesystem writes.
"""
import json
import tempfile
from pathlib import Path

import pytest

from streamforge.drift_detector import (
    EventWindow,
    _load_new_events,
    _route_event_to_cluster,
    _sub_schema_to_inferred_schema,
    detect_drift_multi_schema,
)
from streamforge.models import DriftTier, FieldDrift, FieldSchema, FieldType, InferredSchema
from streamforge.sampler import reservoir_sample


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_profile(clusters: list[dict], discovery_method: str = "event_type_field") -> dict:
    """Minimal profile.yaml dict for testing."""
    return {
        "stream": "test.stream",
        "discovery_method": discovery_method,
        "sub_schemas": clusters,
    }


def _make_cluster(cluster_id: str, fields: list[dict] | None = None) -> dict:
    return {
        "cluster_id": cluster_id,
        "detection_method": "event_type_field",
        "event_count": 100,
        "sample_rate": 0.5,
        "inference_confidence": 0.9,
        "top_keys": ["event_type", "id"],
        "fields": fields or [
            {"path": "event_type", "type": "string", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.99},
            {"path": "id", "type": "uuid", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.98},
            {"path": "amount", "type": "float", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.97},
        ],
    }


# ── EventWindow (P1-B) ───────────────────────────────────────────────────────

class TestEventWindow:
    def test_initial_empty(self):
        w = EventWindow(capacity=100)
        assert len(w) == 0

    def test_add_and_len(self):
        w = EventWindow(capacity=100)
        w.add([{"a": 1}, {"b": 2}])
        assert len(w) == 2

    def test_capacity_evicts_oldest(self):
        w = EventWindow(capacity=3)
        w.add([{"id": 1}, {"id": 2}, {"id": 3}])
        assert len(w) == 3
        w.add([{"id": 4}])
        assert len(w) == 3
        # oldest (id=1) should be evicted; id=4 should be present
        ids = [e["id"] for e in w.events]
        assert 1 not in ids
        assert 4 in ids

    def test_sample_returns_correct_size(self):
        w = EventWindow(capacity=1000)
        w.add([{"x": i} for i in range(500)])
        sample = w.sample(100)
        assert len(sample) == 100

    def test_sample_returns_all_when_window_small(self):
        w = EventWindow(capacity=1000)
        w.add([{"x": i} for i in range(10)])
        sample = w.sample(50)
        assert len(sample) == 10

    def test_add_multiple_batches(self):
        w = EventWindow(capacity=1000)
        w.add([{"id": 1}, {"id": 2}])
        w.add([{"id": 3}])
        assert len(w) == 3


# ── _load_new_events (P1-B) ───────────────────────────────────────────────────

class TestLoadNewEvents:
    def test_loads_all_lines_on_first_call(self, tmp_path):
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\n{"id": 2}\n')
        counts: dict = {}
        events = _load_new_events(str(tmp_path), counts)
        assert len(events) == 2
        assert counts[str(f)] == 2

    def test_does_not_reload_unchanged_lines(self, tmp_path):
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\n{"id": 2}\n')
        counts: dict = {}
        _load_new_events(str(tmp_path), counts)
        # Second call — file unchanged
        events2 = _load_new_events(str(tmp_path), counts)
        assert events2 == []

    def test_picks_up_appended_lines(self, tmp_path):
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\n')
        counts: dict = {}
        _load_new_events(str(tmp_path), counts)
        # Append a new line
        with open(f, "a") as fh:
            fh.write('{"id": 2}\n')
        events2 = _load_new_events(str(tmp_path), counts)
        assert len(events2) == 1
        assert events2[0]["id"] == 2

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\nnot json\n{"id": 2}\n')
        counts: dict = {}
        events = _load_new_events(str(tmp_path), counts)
        assert len(events) == 2

    def test_resets_on_file_truncation(self, tmp_path):
        f = tmp_path / "events.ndjson"
        f.write_text('{"id": 1}\n{"id": 2}\n{"id": 3}\n')
        counts: dict = {}
        _load_new_events(str(tmp_path), counts)
        # Simulate log rotation: file is replaced with fewer lines
        f.write_text('{"id": 10}\n')
        events = _load_new_events(str(tmp_path), counts)
        assert len(events) == 1
        assert events[0]["id"] == 10


# ── Multi-schema routing (P1-A) ───────────────────────────────────────────────

class TestRouteEventToCluster:
    def _two_cluster_profile(self) -> dict:
        return _make_profile([
            _make_cluster("payment_initiated"),
            _make_cluster("payment_completed"),
        ])

    def test_routes_by_event_type(self):
        profile = self._two_cluster_profile()
        event = {"event_type": "payment_initiated", "id": "abc"}
        cid = _route_event_to_cluster(event, profile)
        assert cid == "payment_initiated"

    def test_routes_by_type_field_alias(self):
        profile = _make_profile(
            [_make_cluster("order_placed"), _make_cluster("order_shipped")],
            discovery_method="event_type_field",
        )
        event = {"type": "order_placed", "id": "x"}
        cid = _route_event_to_cluster(event, profile)
        assert cid == "order_placed"

    def test_returns_none_for_unknown_event(self):
        profile = self._two_cluster_profile()
        event = {"event_type": "payment_refunded", "id": "abc"}  # not in known clusters
        cid = _route_event_to_cluster(event, profile)
        assert cid is None

    def test_routes_structural_fingerprint(self):
        import hashlib
        keys = ["amount", "currency", "id"]
        key_sig = "|".join(sorted(keys))
        h = hashlib.sha256(key_sig.encode()).hexdigest()[:12]
        cluster_id = f"struct:{h}"
        profile = _make_profile(
            [_make_cluster(cluster_id)],
            discovery_method="structural_fingerprint",
        )
        event = {"amount": 1.0, "currency": "USD", "id": "x"}
        cid = _route_event_to_cluster(event, profile)
        assert cid == cluster_id


# ── _sub_schema_to_inferred_schema (P1-A) ─────────────────────────────────────

class TestSubSchemaToInferredSchema:
    def test_converts_fields(self):
        cluster = _make_cluster("payment_initiated")
        schema = _sub_schema_to_inferred_schema(cluster, "test.stream")
        assert schema.stream_name == "test.stream/payment_initiated"
        assert len(schema.fields) == 3
        field_paths = [f.path for f in schema.fields]
        assert "amount" in field_paths

    def test_confidence_preserved(self):
        cluster = _make_cluster("x")
        cluster["inference_confidence"] = 0.85
        schema = _sub_schema_to_inferred_schema(cluster, "s")
        assert schema.inference_confidence == 0.85

    def test_pii_fields_parsed(self):
        cluster = _make_cluster("x", fields=[
            {"path": "email", "type": "email", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.99, "pii": ["email"]},
        ])
        schema = _sub_schema_to_inferred_schema(cluster, "s")
        assert schema.fields[0].pii_categories


# ── detect_drift_multi_schema (P1-A) ─────────────────────────────────────────

class TestDetectDriftMultiSchema:
    def _profile_two_clusters(self) -> dict:
        initiated_fields = [
            {"path": "event_type", "type": "string", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.99},
            {"path": "amount", "type": "float", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.97},
        ]
        completed_fields = [
            {"path": "event_type", "type": "string", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.99},
            {"path": "amount", "type": "float", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.97},
            {"path": "receipt_url", "type": "string", "required": True, "nullable": False,
             "presence_rate": 1.0, "confidence": 0.95},
        ]
        return _make_profile([
            _make_cluster("payment_initiated", fields=initiated_fields),
            _make_cluster("payment_completed", fields=completed_fields),
        ])

    def _clean_sample(self, n: int = 50) -> list[dict]:
        sample = []
        for i in range(n // 2):
            sample.append({"event_type": "payment_initiated", "amount": float(i)})
            sample.append({
                "event_type": "payment_completed",
                "amount": float(i),
                "receipt_url": f"https://receipts.example.com/{i}",
            })
        return sample

    def test_clean_sample_returns_no_reports(self):
        profile = self._profile_two_clusters()
        sample = self._clean_sample()
        reports = detect_drift_multi_schema(profile, sample, "test.stream")
        assert reports == []

    def test_detects_drift_in_one_cluster(self):
        profile = self._profile_two_clusters()
        # Inject drift: amount becomes string in payment_initiated events.
        # Use 200+ events per cluster to exceed MIN_CLUSTER_EVENTS_FOR_DRIFT.
        sample = []
        for i in range(200):
            sample.append({"event_type": "payment_initiated", "amount": f"bad_str_{i}"})
        for i in range(200):
            sample.append({
                "event_type": "payment_completed",
                "amount": float(i),
                "receipt_url": f"https://receipts.example.com/{i}",
            })
        reports = detect_drift_multi_schema(profile, sample, "test.stream")
        assert len(reports) >= 1
        affected_clusters = {d.cluster_id for r in reports for d in r.drifts}
        assert "payment_initiated" in affected_clusters

    def test_cluster_id_tagged_on_drifts(self):
        profile = self._profile_two_clusters()
        # Cause drift only in initiated cluster
        sample = [{"event_type": "payment_initiated", "amount": "bad"} for _ in range(20)]
        sample += [
            {"event_type": "payment_completed", "amount": 1.0, "receipt_url": "u"}
            for _ in range(20)
        ]
        reports = detect_drift_multi_schema(profile, sample, "test.stream")
        for report in reports:
            for d in report.drifts:
                if d.cluster_id is not None:
                    assert d.cluster_id in ("payment_initiated", "payment_completed", "__cluster__")

    def test_unknown_events_trigger_new_cluster_drift(self):
        profile = self._profile_two_clusters()
        # 10% known, 90% unknown
        sample = [{"event_type": "payment_initiated", "amount": 1.0}] * 10
        sample += [{"event_type": "payment_refunded", "amount": 2.0}] * 90
        reports = detect_drift_multi_schema(profile, sample, "test.stream")
        new_cluster_reports = [
            r for r in reports
            if any(d.drift_type == "new_cluster" for d in r.drifts)
        ]
        assert len(new_cluster_reports) >= 1

    def test_returns_empty_for_empty_profile(self):
        profile = _make_profile([])
        reports = detect_drift_multi_schema(profile, [{"a": 1}] * 20, "test.stream")
        assert reports == []

    def test_skips_clusters_with_too_few_events(self):
        profile = self._profile_two_clusters()
        # Only 3 events for payment_initiated — below MIN_CLUSTER_EVENTS_FOR_DRIFT
        sample = [{"event_type": "payment_initiated", "amount": "bad"} for _ in range(3)]
        sample += [
            {"event_type": "payment_completed", "amount": 1.0, "receipt_url": "u"}
            for _ in range(30)
        ]
        reports = detect_drift_multi_schema(profile, sample, "test.stream")
        # No drift report for payment_initiated (too few events to compare)
        affected = {d.cluster_id for r in reports for d in r.drifts if d.cluster_id}
        assert "payment_initiated" not in affected


# ── FieldDrift cluster_id field (P1-A model change) ──────────────────────────

class TestFieldDriftClusterId:
    def test_cluster_id_defaults_to_none(self):
        d = FieldDrift(
            field_path="amount",
            drift_type="field_removed",
            affected_event_rate=1.0,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
        )
        assert d.cluster_id is None

    def test_cluster_id_can_be_set(self):
        d = FieldDrift(
            field_path="amount",
            drift_type="field_removed",
            affected_event_rate=1.0,
            tier=DriftTier.TIER_3,
            auto_correctable=False,
            cluster_id="payment_initiated",
        )
        assert d.cluster_id == "payment_initiated"
