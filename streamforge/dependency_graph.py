"""Schema Dependency Graph — cross-topic field correlation + consumer impact.

The moat: after months of monitoring, StreamForge accumulates cross-topic
field usage data that no competitor can replicate without running the product.

Usage:
    graph = SchemaGraph.build(registry, schemas_dir="schemas")
    node = graph.field_usage("user_id")          # which streams use this?
    shared = graph.shared_fields("payments", "bookings")  # fields in common?
    issues = graph.inconsistencies()              # type mismatches?
    impact = graph.blast_radius("payments", "amount", "type_changed")
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    CrossTopicImpact,
    DependencyGraphMeta,
    DriftReport,
    FieldNode,
    FieldUsageEntry,
)

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_PATH = Path(".streamforge/dependency_graph.json")


class SchemaGraph:
    """Cross-topic field dependency graph."""

    def __init__(
        self,
        nodes: dict[str, FieldNode] | None = None,
        meta: DependencyGraphMeta | None = None,
    ) -> None:
        self._nodes: dict[str, FieldNode] = nodes or {}
        self.meta = meta or DependencyGraphMeta()
        self._lock = threading.RLock()

    # ── Build ───────────────────────────────────────────────────────────

    @staticmethod
    def build(registry: Any, schemas_dir: str = "schemas") -> SchemaGraph:
        """Build graph from FieldTypeRegistry + schema files."""
        from .schema_writer import load_schema

        nodes: dict[str, FieldNode] = {}
        all_streams: set[str] = set()
        edge_count = 0

        for field_path, obs in registry._observations.items():
            real_streams = [s for s in obs.stream_names if s and s != "_seed"]
            if not real_streams:
                continue

            usages: list[FieldUsageEntry] = []
            for stream_name in real_streams:
                all_streams.add(stream_name)
                schema_path = Path(schemas_dir) / stream_name / "schema.yaml"
                field_type = obs.field_type
                presence = 1.0
                required = True
                pii: list[str] = []

                if schema_path.exists():
                    try:
                        schema = load_schema(str(schema_path))
                        for f in schema.fields:
                            if f.path == field_path:
                                field_type = f.field_type.value if hasattr(f.field_type, "value") else str(f.field_type)
                                presence = f.presence_rate
                                required = f.required
                                pii = [c.value if hasattr(c, "value") else str(c) for c in f.pii_categories]
                                break
                    except Exception as e:
                        logger.debug("Could not load schema for %s: %s", stream_name, e)

                usages.append(FieldUsageEntry(
                    stream_name=stream_name, field_type=field_type,
                    presence_rate=presence, required=required, pii_categories=pii,
                ))
                edge_count += 1

            types_seen = {u.field_type for u in usages}
            nodes[field_path] = FieldNode(
                field_path=field_path, usages=usages,
                is_inconsistent=len(types_seen) > 1,
            )

        meta = DependencyGraphMeta(
            built_at=datetime.now(UTC).isoformat(),
            stream_count=len(all_streams),
            field_count=len(nodes), edge_count=edge_count,
        )
        logger.info("Schema graph built: %d fields, %d streams, %d inconsistencies",
                     len(nodes), len(all_streams),
                     sum(1 for n in nodes.values() if n.is_inconsistent))
        return SchemaGraph(nodes=nodes, meta=meta)

    @staticmethod
    def from_schemas(schemas_dir: str = "schemas") -> SchemaGraph:
        """Build the graph directly from committed schema.yaml files.

        Unlike build() (which relies on the field registry's stream membership),
        this always reflects the current committed schemas — the right source for
        the cockpit's cross-topic view. A field used in >1 stream with >1 type is
        flagged inconsistent (the cross-topic bugs worth surfacing).
        """
        from .schema_writer import load_schema

        by_field: dict[str, list[FieldUsageEntry]] = {}
        all_streams: set[str] = set()
        edge_count = 0

        for schema_path in sorted(Path(schemas_dir).glob("*/schema.yaml")):
            stream_name = schema_path.parent.name
            try:
                schema = load_schema(str(schema_path))
            except Exception as e:  # noqa: BLE001 — skip unreadable schema, keep going
                logger.debug("Could not load schema for %s: %s", stream_name, e)
                continue
            all_streams.add(stream_name)
            for f in schema.fields:
                ftype = f.field_type.value if hasattr(f.field_type, "value") else str(f.field_type)
                pii = [c.value if hasattr(c, "value") else str(c) for c in f.pii_categories]
                by_field.setdefault(f.path, []).append(FieldUsageEntry(
                    stream_name=stream_name, field_type=ftype,
                    presence_rate=f.presence_rate, required=f.required, pii_categories=pii,
                ))
                edge_count += 1

        nodes: dict[str, FieldNode] = {}
        for field_path, usages in by_field.items():
            types_seen = {u.field_type for u in usages}
            nodes[field_path] = FieldNode(
                field_path=field_path, usages=usages,
                is_inconsistent=len(types_seen) > 1,
            )

        meta = DependencyGraphMeta(
            built_at=datetime.now(UTC).isoformat(),
            stream_count=len(all_streams),
            field_count=len(nodes), edge_count=edge_count,
        )
        return SchemaGraph(nodes=nodes, meta=meta)

    # ── Queries ─────────────────────────────────────────────────────────

    def field_usage(self, field_path: str) -> FieldNode | None:
        return self._nodes.get(field_path)

    def shared_fields(self, stream_a: str, stream_b: str) -> list[str]:
        fields_a: set[str] = set()
        fields_b: set[str] = set()
        for path, node in self._nodes.items():
            names = node.stream_names
            if stream_a in names:
                fields_a.add(path)
            if stream_b in names:
                fields_b.add(path)
        return sorted(fields_a & fields_b)

    def inconsistencies(self) -> list[FieldNode]:
        return [n for n in self._nodes.values() if n.is_inconsistent]

    def blast_radius(
        self, stream: str, field_path: str, drift_type: str,
        schemas_dir: str = "schemas",
    ) -> CrossTopicImpact:
        node = self._nodes.get(field_path)
        if node is None:
            return CrossTopicImpact(field_path=field_path, drift_type=drift_type, source_stream=stream)

        other = [u.stream_name for u in node.usages if u.stream_name != stream]
        type_map = {u.stream_name: u.field_type for u in node.usages if u.stream_name != stream}

        consumers: list[str] = []
        try:
            from .consumer_registry import load_consumers
            for s in [stream] + other:
                for c in load_consumers(schemas_dir, s):
                    name = getattr(c, "name", None)
                    if name and name not in consumers:
                        consumers.append(name)
        except Exception:
            pass

        return CrossTopicImpact(
            field_path=field_path, drift_type=drift_type, source_stream=stream,
            also_in_streams=other, type_in_other_streams=type_map,
            consumer_services=consumers,
        )

    def field_lineage(self, field_path: str, schemas_dir: str = "schemas") -> dict[str, Any]:
        node = self._nodes.get(field_path)
        if node is None:
            return {"field_path": field_path, "streams": [], "found": False}

        streams_info = []
        for usage in node.usages:
            info: dict[str, Any] = {
                "stream": usage.stream_name, "type": usage.field_type,
                "presence_rate": usage.presence_rate, "required": usage.required,
                "pii": usage.pii_categories, "consumers": [],
            }
            try:
                from .consumer_registry import load_consumers
                for c in load_consumers(schemas_dir, usage.stream_name):
                    info["consumers"].append({
                        "name": getattr(c, "name", "unknown"),
                        "team": getattr(c, "team", "unknown"),
                        "criticality": getattr(c, "criticality", "unknown"),
                    })
            except Exception:
                pass
            streams_info.append(info)

        return {
            "field_path": field_path, "found": True,
            "stream_count": len(streams_info),
            "is_inconsistent": node.is_inconsistent,
            "streams": streams_info,
        }

    def enrich_drift_report(self, report: DriftReport, schemas_dir: str = "schemas") -> list[CrossTopicImpact]:
        impacts = []
        for drift in report.drifts:
            impact = self.blast_radius(report.stream_name, drift.field_path, drift.drift_type, schemas_dir)
            if impact.also_in_streams:
                impacts.append(impact)
        return impacts

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> None:
        target = path or _DEFAULT_GRAPH_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "meta": self.meta.model_dump(mode="json"),
            "nodes": {k: v.model_dump(mode="json") for k, v in sorted(self._nodes.items())},
        }
        lock_path = target.with_suffix(".lock")
        try:
            lock_fd = open(lock_path, "w")  # noqa: SIM115 — flock fd held across locked region, closed in finally
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                tmp = target.with_suffix(".tmp")
                fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
                try:
                    os.write(fd, json.dumps(data, indent=2, default=str).encode("utf-8"))
                finally:
                    os.close(fd)
                tmp.replace(target)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
        except OSError as e:
            logger.warning("Failed to save schema graph: %s", e)

    @staticmethod
    def load(path: Path | None = None) -> SchemaGraph | None:
        target = path or _DEFAULT_GRAPH_PATH
        if not target.exists():
            return None
        lock_path = target.with_suffix(".lock")
        try:
            lock_fd = open(lock_path, "w")  # noqa: SIM115 — flock fd held across locked region, closed in finally
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                meta = DependencyGraphMeta(**raw.get("meta", {}))
                nodes = {k: FieldNode(**v) for k, v in raw.get("nodes", {}).items()}
                return SchemaGraph(nodes=nodes, meta=meta)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Failed to load schema graph: %s", e)
            return None

    # ── Convenience ─────────────────────────────────────────────────────

    @property
    def field_count(self) -> int:
        return len(self._nodes)

    @property
    def all_field_paths(self) -> list[str]:
        return sorted(self._nodes.keys())

    def streams_for_field(self, field_path: str) -> list[str]:
        node = self._nodes.get(field_path)
        return node.stream_names if node else []
