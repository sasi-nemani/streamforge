"""State store for reading StreamForge data from Redis or files."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Redis is optional — fallback to file-based state
try:
    import redis
    _redis_available = True
except ImportError:
    _redis_available = False


class Store:
    """Unified interface for reading StreamForge state."""

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._schema_dir = Path(os.environ.get("STREAMFORGE_SCHEMA_DIR", "schemas"))
        self._init_redis()

    def _init_redis(self):
        if not _redis_available:
            return
        redis_url = os.environ.get("STREAMFORGE_REDIS_URL")
        if redis_url:
            try:
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    def get_sources(self) -> list[dict]:
        """Get list of connected sources with status."""
        sources = []
        for schema_path in self._schema_dir.glob("*/schema.yaml"):
            stream_dir = schema_path.parent
            health_file = stream_dir / ".watch_state" / "health.json"

            source = {
                "name": stream_dir.name,
                "type": "kafka",  # default, could be file/sftp
                "uri": f"kafka://{stream_dir.name}",
                "status": "unknown",
                "last_seen": None,
                "messages_sampled": 0,
            }

            if health_file.exists():
                try:
                    health = json.loads(health_file.read_text())
                    source["status"] = health.get("status", "unknown")
                    source["last_seen"] = health.get("timestamp")
                    metrics = health.get("metrics", {})
                    source["messages_sampled"] = int(metrics.get("events_sampled_total", 0))
                except Exception:
                    pass

            sources.append(source)
        return sources

    def get_metrics_summary(self) -> dict:
        """Get aggregated metrics across all sources."""
        total_messages = 0
        total_fields = 0
        total_schemas = 0
        total_pii = 0
        active_drifts = 0
        total_poll_cycles = 0
        total_drift_detected = 0

        for schema_path in self._schema_dir.glob("*/schema.yaml"):
            total_schemas += 1
            stream_dir = schema_path.parent

            try:
                schema = yaml.safe_load(schema_path.read_text())
                fields = schema.get("fields", [])
                total_fields += len(fields)
                total_pii += sum(1 for f in fields if f.get("pii"))

                # Try to get LIVE metrics from health.json first
                health_file = stream_dir / ".watch_state" / "health.json"
                if health_file.exists():
                    try:
                        health = json.loads(health_file.read_text())
                        metrics = health.get("metrics", {})
                        total_messages += int(metrics.get("events_sampled_total", 0))
                        total_poll_cycles += int(metrics.get("poll_cycles_total", 0))
                        total_drift_detected += int(metrics.get("drift_detected_total", 0))
                    except Exception:
                        # Fallback to schema if health.json parse fails
                        total_messages += schema.get("event_count_sampled", 0)
                else:
                    # Fallback to static schema count if no health.json
                    total_messages += schema.get("event_count_sampled", 0)
            except Exception:
                pass

            # Count active drifts
            drift_dir = stream_dir / "drift_reports"
            if drift_dir.exists():
                active_drifts += len(list(drift_dir.glob("*.md")))

        return {
            "messages_sampled": total_messages,
            "fields_detected": total_fields,
            "schemas_inferred": total_schemas,
            "pii_fields": total_pii,
            "active_drifts": active_drifts,
            "poll_cycles": total_poll_cycles,
            "drift_detected": total_drift_detected,
        }

    def get_active_drifts(self) -> list[dict]:
        """Get list of active drift alerts."""
        drifts = []
        for schema_path in self._schema_dir.glob("*/schema.yaml"):
            drift_dir = schema_path.parent / "drift_reports"
            if not drift_dir.exists():
                continue

            for report_path in sorted(drift_dir.glob("*.md"), reverse=True)[:10]:
                drifts.append({
                    "stream": schema_path.parent.name,
                    "report": report_path.name,
                    "detected_at": datetime.fromtimestamp(
                        report_path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
        return drifts

    def get_pii_summary(self) -> dict:
        """Get PII field summary by category."""
        by_category: dict[str, int] = {}
        total = 0

        for schema_path in self._schema_dir.glob("*/schema.yaml"):
            try:
                schema = yaml.safe_load(schema_path.read_text())
                for field in schema.get("fields", []):
                    pii = field.get("pii", [])
                    if pii:
                        total += 1
                        for category in pii:
                            by_category[category] = by_category.get(category, 0) + 1
            except Exception:
                pass

        return {"total": total, "by_category": by_category}

    def check_health(self, component: str) -> dict:
        """Check health of a specific component."""
        start = datetime.now(timezone.utc)
        status = "ok"
        error = None

        if component == "redis":
            if self._redis:
                try:
                    self._redis.ping()
                except Exception as e:
                    status = "error"
                    error = str(e)
            else:
                status = "unavailable"
                error = "Redis not configured"
        elif component == "schemas":
            if not self._schema_dir.exists():
                status = "error"
                error = f"Schema dir not found: {self._schema_dir}"

        latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return {"name": component, "status": status, "latency_ms": round(latency, 2), "error": error}


# Singleton instance
_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
