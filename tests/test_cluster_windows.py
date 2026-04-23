"""Tests for per-cluster windows, source abstraction, auto-mode, and auto-export.

Citadel design: undiluted samples, automatic mode, source-agnostic, hands-off.
"""

import json
from pathlib import Path
from typing import Any

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: Per-cluster EventWindow map
# ═══════════════════════════════════════════════════════════════════════════════

class TestClusterWindowMap:
    """Each cluster gets its own window — no dilution."""

    def test_cluster_window_map_routes_events(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["payment.created", "payment.failed"],
            routing_field="event_type",
            capacity=100,
        )
        cwm.add([
            {"event_type": "payment.created", "id": 1},
            {"event_type": "payment.failed", "id": 2},
            {"event_type": "payment.created", "id": 3},
        ])
        assert len(cwm.windows["payment.created"]) == 2
        assert len(cwm.windows["payment.failed"]) == 1

    def test_cluster_window_map_unknown_events_auto_discovered(self):
        """Unknown event types get auto-created as new cluster windows (dynamic discovery)."""
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["payment.created"],
            routing_field="event_type",
            capacity=100,
        )
        cwm.add([
            {"event_type": "payment.created", "id": 1},
            {"event_type": "payment.new_type", "id": 2},
        ])
        assert len(cwm.windows["payment.created"]) == 1
        assert "payment.new_type" in cwm.windows
        assert len(cwm.windows["payment.new_type"]) == 1
        assert len(cwm.unrouted) == 0

    def test_cluster_window_map_unknown_events_go_to_unrouted_when_at_max(self):
        """When max_clusters is reached, unknown events go to unrouted."""
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["payment.created"],
            routing_field="event_type",
            capacity=100,
            max_clusters=1,
        )
        cwm.add([
            {"event_type": "payment.created", "id": 1},
            {"event_type": "payment.new_type", "id": 2},
        ])
        assert len(cwm.windows["payment.created"]) == 1
        assert "payment.new_type" not in cwm.windows
        assert len(cwm.unrouted) == 1

    def test_cluster_window_sample_undiluted(self):
        """Each cluster gets full sample_size, not sample_size / n_clusters."""
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["a", "b"],
            routing_field="type",
            capacity=1000,
        )
        # Add 500 events per cluster
        events_a = [{"type": "a", "id": i} for i in range(500)]
        events_b = [{"type": "b", "id": i} for i in range(500)]
        cwm.add(events_a + events_b)

        # Sample 200 from each — NOT 200 split across both
        sample_a = cwm.sample_cluster("a", 200)
        sample_b = cwm.sample_cluster("b", 200)
        assert len(sample_a) == 200
        assert len(sample_b) == 200

    def test_cluster_window_falls_back_to_single_for_one_cluster(self):
        """With 1 cluster, behaves identically to single-schema mode."""
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["payment"],
            routing_field="event_type",
            capacity=1000,
        )
        cwm.add([{"event_type": "payment", "id": i} for i in range(100)])
        sample = cwm.sample_cluster("payment", 50)
        assert len(sample) == 50

    def test_cluster_window_total_count(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["a", "b"],
            routing_field="type",
            capacity=100,
        )
        cwm.add([{"type": "a"}, {"type": "b"}, {"type": "a"}])
        assert cwm.total_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: Source abstraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestStreamSource:
    """StreamSource protocol — any connector can be plugged in."""

    def test_protocol_exists(self):
        from streamforge.connectors.protocol import StreamSource
        # Should be importable
        assert StreamSource is not None

    def test_ndjson_source_implements_protocol(self):
        """File-based source must implement StreamSource."""
        from streamforge.connectors.protocol import NdjsonSource
        source = NdjsonSource.__new__(NdjsonSource)
        assert hasattr(source, "read_batch")
        assert hasattr(source, "ack")

    def test_ndjson_source_reads_events(self, tmp_path):
        from streamforge.connectors.protocol import NdjsonSource
        f = tmp_path / "events.ndjson"
        f.write_text("\n".join(json.dumps({"id": i}) for i in range(10)))
        source = NdjsonSource(str(tmp_path))
        events = source.read_batch(max_messages=5)
        assert len(events) == 5
        assert events[0]["id"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: Auto-export on init
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoExportOnInit:
    """streamforge init must produce all 4 artifact formats automatically."""

    def test_init_produces_all_formats(self, tmp_path):
        """After init, the schema directory must contain yaml + json + avsc + md."""
        from streamforge.models import FieldSchema, FieldType, InferredSchema
        from streamforge.schema_writer import write_schema_with_exports

        schema = InferredSchema(
            stream_name="test", version="1.0.0",
            inferred_at="2026-04-03T10:00:00Z", event_count_sampled=100,
            fields=[
                FieldSchema(name="id", path="id", field_type=FieldType.UUID,
                            required=True, presence_rate=1.0, confidence=0.9),
                FieldSchema(name="status", path="status", field_type=FieldType.STRING,
                            required=True, presence_rate=1.0, confidence=0.9,
                            enum_values=["active", "inactive"]),
            ],
            inference_model="test", inference_confidence=0.9,
        )
        paths = write_schema_with_exports(schema, str(tmp_path))

        assert (tmp_path / "test" / "schema.yaml").exists()
        assert (tmp_path / "test" / "schema.json").exists()
        assert (tmp_path / "test" / "schema.avsc").exists()
        assert (tmp_path / "test" / "DATA_DICTIONARY.md").exists()

        # JSON Schema must have enum
        js = json.loads((tmp_path / "test" / "schema.json").read_text())
        assert js["properties"]["status"]["enum"] == ["active", "inactive"]

        # Avro must have native enum
        avro = json.loads((tmp_path / "test" / "schema.avsc").read_text())
        status_field = next(f for f in avro["fields"] if f["name"] == "status")
        assert isinstance(status_field["type"], dict)
        assert status_field["type"]["type"] == "enum"

        # Markdown must be readable
        md = (tmp_path / "test" / "DATA_DICTIONARY.md").read_text()
        assert "active" in md
        assert "inactive" in md
