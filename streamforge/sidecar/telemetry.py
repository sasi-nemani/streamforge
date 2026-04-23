"""
streamforge/sidecar/telemetry.py — Sidecar Telemetry & Audit
=============================================================

Full observability for sidecar operations. Every action is auditable.

Audit events capture:
- WHAT: operation performed, queue, message details
- WHEN: precise timestamp
- HOW: method, parameters, result, errors

Core principle: NEVER touch or modify messages. NEVER alter queue state.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from io import StringIO
from typing import Any, TextIO

from .models import TelemetryOperation


class SidecarAudit:
    """
    Structured audit logger for sidecar operations.

    All audit events are emitted as JSON lines for machine parsing.
    Thread-safe for concurrent logging.
    """

    def __init__(self, output_stream: TextIO | None = None) -> None:
        self._output = output_stream or StringIO()
        self._lock = threading.Lock()

    def _emit(self, event: dict[str, Any]) -> None:
        """Emit a structured JSON audit event."""
        event["ts"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        line = json.dumps(event, default=str) + "\n"
        with self._lock:
            self._output.write(line)

    def log_operation(
        self,
        operation: TelemetryOperation,
        queue_name: str,
        success: bool,
        messages_observed: int,
        latency_ms: float,
        error_code: str | None = None,
        error_message: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        """Log a sidecar operation (peek, browse, etc.)."""
        event = {
            "audit": "sidecar_operation",
            "operation": operation.value,
            "queue_name": queue_name,
            "success": success,
            "messages_observed": messages_observed,
            "latency_ms": latency_ms,
        }
        if error_code:
            event["error_code"] = error_code
        if error_message:
            event["error_message"] = error_message
        if batch_id:
            event["batch_id"] = batch_id
        self._emit(event)

    def log_observation(
        self,
        queue_name: str,
        message_id: str,
        observation_method: str,
        payload_size_bytes: int = 0,
        message_attributes: dict[str, Any] | None = None,
    ) -> None:
        """Log an individual message observation."""
        event = {
            "audit": "sidecar_observation",
            "queue_name": queue_name,
            "message_id": message_id,
            "observation_method": observation_method,
            "payload_size_bytes": payload_size_bytes,
        }
        if message_attributes:
            event["message_attributes"] = message_attributes
        self._emit(event)

    def log_batch_start(
        self,
        batch_id: str,
        queue_name: str,
        max_messages: int,
    ) -> None:
        """Log the start of a batch observation."""
        self._emit({
            "audit": "sidecar_batch_start",
            "batch_id": batch_id,
            "queue_name": queue_name,
            "max_messages": max_messages,
        })

    def log_batch_complete(
        self,
        batch_id: str,
        queue_name: str,
        messages_observed: int,
        duration_ms: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Log completion of a batch observation."""
        event = {
            "audit": "sidecar_batch_complete",
            "batch_id": batch_id,
            "queue_name": queue_name,
            "messages_observed": messages_observed,
            "duration_ms": duration_ms,
            "success": success,
        }
        if error_message:
            event["error_message"] = error_message
        self._emit(event)


class MetricsCollector:
    """
    Metrics collector for sidecar operations.

    Thread-safe counters and histograms for monitoring.
    Exports in Prometheus format.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._operations: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "success": 0, "failure": 0}
        )
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._queues: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total_observed": 0, "batch_count": 0}
        )

    def record_operation(
        self,
        operation: TelemetryOperation,
        success: bool,
    ) -> None:
        """Record an operation count."""
        with self._lock:
            self._operations[operation.value]["total"] += 1
            if success:
                self._operations[operation.value]["success"] += 1
            else:
                self._operations[operation.value]["failure"] += 1

    def record_latency(
        self,
        operation: TelemetryOperation,
        latency_ms: float,
    ) -> None:
        """Record operation latency."""
        with self._lock:
            self._latencies[operation.value].append(latency_ms)

    def record_messages_observed(
        self,
        queue_name: str,
        count: int,
    ) -> None:
        """Record messages observed from a queue."""
        with self._lock:
            self._queues[queue_name]["total_observed"] += count
            self._queues[queue_name]["batch_count"] += 1

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics."""
        with self._lock:
            latency_stats = {}
            for op, values in self._latencies.items():
                if values:
                    latency_stats[op] = {
                        "count": len(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                    }
                else:
                    latency_stats[op] = {"count": 0, "avg": 0, "min": 0, "max": 0}

            return {
                "operations": dict(self._operations),
                "latency": latency_stats,
                "queues": dict(self._queues),
            }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        stats = self.get_stats()

        # Operations
        lines.append("# HELP streamforge_sidecar_operations_total Total sidecar operations")
        lines.append("# TYPE streamforge_sidecar_operations_total counter")
        for op, counts in stats["operations"].items():
            lines.append(
                f'streamforge_sidecar_operations_total{{operation="{op}",status="success"}} {counts["success"]}'
            )
            lines.append(
                f'streamforge_sidecar_operations_total{{operation="{op}",status="failure"}} {counts["failure"]}'
            )

        # Latency
        lines.append("# HELP streamforge_sidecar_latency_ms Operation latency in milliseconds")
        lines.append("# TYPE streamforge_sidecar_latency_ms gauge")
        for op, lat in stats["latency"].items():
            lines.append(f'streamforge_sidecar_latency_ms{{operation="{op}",stat="avg"}} {lat["avg"]}')
            lines.append(f'streamforge_sidecar_latency_ms{{operation="{op}",stat="min"}} {lat["min"]}')
            lines.append(f'streamforge_sidecar_latency_ms{{operation="{op}",stat="max"}} {lat["max"]}')

        # Messages observed
        lines.append("# HELP streamforge_sidecar_messages_observed_total Total messages observed")
        lines.append("# TYPE streamforge_sidecar_messages_observed_total counter")
        for queue, data in stats["queues"].items():
            lines.append(
                f'streamforge_sidecar_messages_observed_total{{queue="{queue}"}} {data["total_observed"]}'
            )

        return "\n".join(lines)


class TelemetryContext:
    """Context for automatic telemetry collection."""

    def __init__(self, operation: TelemetryOperation, queue_name: str) -> None:
        self.operation = operation
        self.queue_name = queue_name
        self.success = True
        self.messages_observed = 0
        self.error_message: str | None = None
        self.error_code: str | None = None
        self._start_time: float = 0
        self._end_time: float = 0

    @property
    def latency_ms(self) -> float:
        """Operation latency in milliseconds."""
        return (self._end_time - self._start_time) * 1000


@contextmanager
def telemetry_context(
    operation: TelemetryOperation,
    queue_name: str,
):
    """
    Context manager for automatic telemetry collection.

    Usage:
        with telemetry_context(TelemetryOperation.PEEK, "my-queue") as ctx:
            messages = await sidecar.peek()
            ctx.messages_observed = len(messages)
    """
    ctx = TelemetryContext(operation, queue_name)
    ctx._start_time = time.perf_counter()

    try:
        yield ctx
        ctx.success = True
    except Exception as e:
        ctx.success = False
        ctx.error_message = str(e)
        ctx.error_code = type(e).__name__
        raise
    finally:
        ctx._end_time = time.perf_counter()
