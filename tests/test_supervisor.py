"""Tests for multi-stream supervisor and dynamic cluster discovery."""
import time
import multiprocessing
from pathlib import Path
from unittest.mock import patch
import pytest
from streamforge.models import StreamAssignment, SupervisorConfig


class TestSupervisorConfig:
    def test_stream_assignment_model(self):
        sa = StreamAssignment(stream_uri="events/payments", schema_path="schemas/payments/schema.yaml")
        assert sa.namespace == "default"
        assert sa.poll_interval_seconds == 30

    def test_supervisor_config_model(self):
        cfg = SupervisorConfig(
            assignments=[
                StreamAssignment(stream_uri="events/a", schema_path="schemas/a/schema.yaml"),
                StreamAssignment(stream_uri="events/b", schema_path="schemas/b/schema.yaml"),
            ],
        )
        assert len(cfg.assignments) == 2
        assert cfg.restart_delay_seconds == 5
        assert cfg.max_restart_count == 10

    def test_supervisor_creates_worker_states(self):
        from streamforge.supervisor import Supervisor
        cfg = SupervisorConfig(
            assignments=[
                StreamAssignment(stream_uri="events/a", schema_path="s/a.yaml"),
            ],
        )
        sup = Supervisor(cfg)
        assert "events/a" in sup.workers
        assert sup.workers["events/a"].status == "pending"


class TestDynamicClusterDiscovery:
    def test_new_cluster_auto_created(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["payment.created"],
            routing_field="event_type",
            capacity=100,
            max_clusters=10,
        )
        # Add event with unknown type — should auto-create window
        cwm.add([{"event_type": "payment.refunded", "id": 1}])
        assert "payment.refunded" in cwm.windows
        assert len(cwm.windows["payment.refunded"]) == 1

    def test_max_clusters_limit_enforced(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["seed"],
            routing_field="type",
            capacity=100,
            max_clusters=3,
        )
        cwm.add([
            {"type": "a", "id": 1},
            {"type": "b", "id": 2},
            {"type": "overflow", "id": 3},  # 4th cluster (seed + a + b = 3) → unrouted
        ])
        assert "a" in cwm.windows
        assert "b" in cwm.windows
        assert "overflow" not in cwm.windows
        assert len(cwm.unrouted) == 1

    def test_existing_clusters_still_route(self):
        from streamforge.detector.window import ClusterWindowMap
        cwm = ClusterWindowMap(
            cluster_ids=["a", "b"],
            routing_field="type",
            capacity=100,
        )
        cwm.add([{"type": "a", "id": 1}, {"type": "b", "id": 2}])
        assert len(cwm.windows["a"]) == 1
        assert len(cwm.windows["b"]) == 1
