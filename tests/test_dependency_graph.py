"""Tests for Schema Dependency Graph — the moat feature.

Covers: build, query, persistence, enrichment, edge cases, thread safety.
"""
import os
import stat
import threading
from datetime import UTC, datetime

from streamforge.dependency_graph import SchemaGraph
from streamforge.models import (
    DependencyGraphMeta,
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldNode,
    FieldUsageEntry,
)


def _make_graph():
    """Helper: graph with known test data — 3 fields across 3 streams."""
    nodes = {
        "user_id": FieldNode(
            field_path="user_id",
            usages=[
                FieldUsageEntry(stream_name="payments", field_type="uuid", presence_rate=1.0, required=True),
                FieldUsageEntry(stream_name="bookings", field_type="uuid", presence_rate=0.95, required=True),
                FieldUsageEntry(stream_name="analytics", field_type="uuid", presence_rate=0.90, required=False),
            ],
        ),
        "amount": FieldNode(
            field_path="amount",
            usages=[
                FieldUsageEntry(stream_name="payments", field_type="float", presence_rate=1.0, required=True),
                FieldUsageEntry(stream_name="bookings", field_type="integer", presence_rate=1.0, required=True),
            ],
            is_inconsistent=True,
        ),
        "event_id": FieldNode(
            field_path="event_id",
            usages=[
                FieldUsageEntry(stream_name="payments", field_type="uuid", presence_rate=1.0, required=True),
            ],
        ),
    }
    meta = DependencyGraphMeta(
        built_at=datetime.now(UTC).isoformat(),
        stream_count=3, field_count=3, edge_count=6,
    )
    return SchemaGraph(nodes=nodes, meta=meta)


# ═══════════════════════════════════════════════════════════════════════════════
# Field Usage
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldUsage:
    def test_found(self):
        g = _make_graph()
        node = g.field_usage("user_id")
        assert node is not None
        assert node.stream_count == 3
        assert "payments" in node.stream_names

    def test_not_found(self):
        assert _make_graph().field_usage("nonexistent") is None

    def test_stream_names_property(self):
        node = _make_graph().field_usage("user_id")
        assert set(node.stream_names) == {"payments", "bookings", "analytics"}

    def test_single_stream_field(self):
        node = _make_graph().field_usage("event_id")
        assert node.stream_count == 1
        assert node.stream_names == ["payments"]


# ═══════════════════════════════════════════════════════════════════════════════
# Shared Fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharedFields:
    def test_overlap(self):
        shared = _make_graph().shared_fields("payments", "bookings")
        assert "user_id" in shared
        assert "amount" in shared

    def test_no_overlap(self):
        assert _make_graph().shared_fields("bookings", "nonexistent") == []

    def test_exclusive_field_excluded(self):
        shared = _make_graph().shared_fields("payments", "analytics")
        assert "event_id" not in shared
        assert "user_id" in shared

    def test_same_stream(self):
        shared = _make_graph().shared_fields("payments", "payments")
        assert len(shared) == 3  # all 3 fields


# ═══════════════════════════════════════════════════════════════════════════════
# Inconsistencies
# ═══════════════════════════════════════════════════════════════════════════════

class TestInconsistencies:
    def test_finds_type_mismatch(self):
        issues = _make_graph().inconsistencies()
        assert len(issues) == 1
        assert issues[0].field_path == "amount"

    def test_no_issues_when_consistent(self):
        nodes = {"id": FieldNode(field_path="id", usages=[
            FieldUsageEntry(stream_name="a", field_type="uuid"),
            FieldUsageEntry(stream_name="b", field_type="uuid"),
        ])}
        assert SchemaGraph(nodes=nodes).inconsistencies() == []


# ═══════════════════════════════════════════════════════════════════════════════
# Blast Radius
# ═══════════════════════════════════════════════════════════════════════════════

class TestBlastRadius:
    def test_cross_topic_impact(self):
        impact = _make_graph().blast_radius("payments", "user_id", "type_changed")
        assert "bookings" in impact.also_in_streams
        assert "analytics" in impact.also_in_streams
        assert impact.source_stream == "payments"
        assert impact.type_in_other_streams["bookings"] == "uuid"

    def test_single_stream_no_impact(self):
        impact = _make_graph().blast_radius("payments", "event_id", "field_removed")
        assert impact.also_in_streams == []

    def test_unknown_field(self):
        impact = _make_graph().blast_radius("payments", "unknown", "type_changed")
        assert impact.also_in_streams == []
        assert impact.field_path == "unknown"

    def test_impact_excludes_source_stream(self):
        impact = _make_graph().blast_radius("payments", "user_id", "type_changed")
        assert "payments" not in impact.also_in_streams


# ═══════════════════════════════════════════════════════════════════════════════
# Field Lineage
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldLineage:
    def test_found(self):
        lineage = _make_graph().field_lineage("user_id")
        assert lineage["found"] is True
        assert lineage["stream_count"] == 3
        assert len(lineage["streams"]) == 3

    def test_not_found(self):
        lineage = _make_graph().field_lineage("nonexistent")
        assert lineage["found"] is False
        assert lineage["streams"] == []

    def test_lineage_includes_type_per_stream(self):
        lineage = _make_graph().field_lineage("amount")
        types = {s["stream"]: s["type"] for s in lineage["streams"]}
        assert types["payments"] == "float"
        assert types["bookings"] == "integer"

    def test_lineage_flags_inconsistency(self):
        lineage = _make_graph().field_lineage("amount")
        assert lineage["is_inconsistent"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Enrich Drift Report
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnrichDriftReport:
    def test_enriches_cross_topic(self):
        report = DriftReport(
            stream_name="payments", schema_version="1.0.0",
            detected_at=datetime.now(UTC).isoformat(),
            events_sampled=200, summary="test drift",
            highest_tier=DriftTier.TIER_3,
            drifts=[FieldDrift(
                field_path="user_id", drift_type="type_changed",
                affected_event_rate=1.0, tier=DriftTier.TIER_3, auto_correctable=False,
            )],
        )
        impacts = _make_graph().enrich_drift_report(report)
        assert len(impacts) == 1
        assert "bookings" in impacts[0].also_in_streams

    def test_no_enrichment_for_exclusive_field(self):
        report = DriftReport(
            stream_name="payments", schema_version="1.0.0",
            detected_at=datetime.now(UTC).isoformat(),
            events_sampled=200, summary="test",
            highest_tier=DriftTier.TIER_2,
            drifts=[FieldDrift(
                field_path="event_id", drift_type="field_removed",
                affected_event_rate=1.0, tier=DriftTier.TIER_2, auto_correctable=False,
            )],
        )
        impacts = _make_graph().enrich_drift_report(report)
        assert len(impacts) == 0

    def test_multiple_drifts_enriched(self):
        report = DriftReport(
            stream_name="payments", schema_version="1.0.0",
            detected_at=datetime.now(UTC).isoformat(),
            events_sampled=200, summary="multi",
            highest_tier=DriftTier.TIER_3,
            drifts=[
                FieldDrift(field_path="user_id", drift_type="type_changed",
                           affected_event_rate=1.0, tier=DriftTier.TIER_3, auto_correctable=False),
                FieldDrift(field_path="amount", drift_type="type_changed",
                           affected_event_rate=1.0, tier=DriftTier.TIER_3, auto_correctable=False),
            ],
        )
        impacts = _make_graph().enrich_drift_report(report)
        assert len(impacts) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        graph = _make_graph()
        path = tmp_path / "graph.json"
        graph.save(path)
        loaded = SchemaGraph.load(path)
        assert loaded is not None
        assert loaded.field_count == 3
        assert loaded.field_usage("user_id").stream_count == 3
        assert loaded.field_usage("amount").is_inconsistent is True

    def test_load_missing(self, tmp_path):
        assert SchemaGraph.load(tmp_path / "nope.json") is None

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{broken!!")
        assert SchemaGraph.load(path) is None

    def test_no_tmp_remains(self, tmp_path):
        path = tmp_path / "graph.json"
        _make_graph().save(path)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_permissions_0600(self, tmp_path):
        path = tmp_path / "graph.json"
        _make_graph().save(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "graph.json"
        _make_graph().save(path)
        assert path.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_graph_queries(self):
        g = SchemaGraph()
        assert g.field_usage("x") is None
        assert g.shared_fields("a", "b") == []
        assert g.inconsistencies() == []
        assert g.field_count == 0
        assert g.all_field_paths == []

    def test_field_with_50_streams(self):
        usages = [FieldUsageEntry(stream_name=f"s{i}", field_type="string") for i in range(50)]
        nodes = {"popular": FieldNode(field_path="popular", usages=usages)}
        g = SchemaGraph(nodes=nodes)
        assert g.field_usage("popular").stream_count == 50

    def test_thread_safe_reads(self):
        g = _make_graph()
        errors = []
        def reader():
            try:
                for _ in range(100):
                    g.field_usage("user_id")
                    g.shared_fields("payments", "bookings")
                    g.inconsistencies()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_build_empty_registry(self):
        from streamforge.field_registry import FieldTypeRegistry
        g = SchemaGraph.build(FieldTypeRegistry(), schemas_dir="/nonexistent")
        assert g.field_count == 0

    def test_streams_for_field_convenience(self):
        g = _make_graph()
        assert set(g.streams_for_field("user_id")) == {"payments", "bookings", "analytics"}
        assert g.streams_for_field("nonexistent") == []

    def test_blast_radius_preserves_drift_type(self):
        impact = _make_graph().blast_radius("payments", "user_id", "new_pii")
        assert impact.drift_type == "new_pii"

    def test_inconsistency_detection_three_types(self):
        nodes = {"mixed": FieldNode(
            field_path="mixed",
            usages=[
                FieldUsageEntry(stream_name="a", field_type="string"),
                FieldUsageEntry(stream_name="b", field_type="integer"),
                FieldUsageEntry(stream_name="c", field_type="float"),
            ],
            is_inconsistent=True,
        )}
        g = SchemaGraph(nodes=nodes)
        issues = g.inconsistencies()
        assert len(issues) == 1
        assert issues[0].field_path == "mixed"
