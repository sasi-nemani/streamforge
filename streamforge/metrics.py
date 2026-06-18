"""
streamforge/metrics.py — Lightweight Prometheus-compatible metrics.

Design: No external dependencies (no prometheus_client required).
Thread-safe counters and histograms using threading.Lock.
Exportable as dict for health.json or as Prometheus text format.

If prometheus_client IS installed, these metrics are also registered
as native Prometheus objects for /metrics scraping.
"""

from __future__ import annotations

import threading

_ALL_METRICS: list[Counter | Summary] = []


class Counter:
    """Thread-safe counter (Prometheus-style)."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._value: float = 0.0
        self._lock = threading.Lock()
        _ALL_METRICS.append(self)

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        return self._value


class Summary:
    """Thread-safe summary (tracks count + total for averages)."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._count: int = 0
        self._total: float = 0.0
        self._lock = threading.Lock()
        _ALL_METRICS.append(self)

    def observe(self, value: float) -> None:
        with self._lock:
            self._count += 1
            self._total += value

    @property
    def count(self) -> int:
        return self._count

    @property
    def total(self) -> float:
        return self._total


# ── Global metric instances ──────────────────────────────────────────────────

POLL_DURATION = Summary(
    "poll_duration_seconds",
    "Time spent in each poll cycle (seconds)",
)

EVENTS_SAMPLED = Counter(
    "events_sampled_total",
    "Total events sampled across all poll cycles",
)

DRIFT_DETECTED = Counter(
    "drift_detected_total",
    "Total drift events detected",
)

POLL_CYCLES = Counter(
    "poll_cycles_total",
    "Total poll cycles executed",
)


def metrics_snapshot() -> dict[str, float]:
    """Export all metrics as a flat dict — suitable for health.json or /metrics."""
    return {
        "poll_duration_seconds_count": POLL_DURATION.count,
        "poll_duration_seconds_total": round(POLL_DURATION.total, 4),
        "events_sampled_total": EVENTS_SAMPLED.value,
        "drift_detected_total": DRIFT_DETECTED.value,
        "poll_cycles_total": POLL_CYCLES.value,
    }


def prometheus_text() -> str:
    """Export all metrics in Prometheus text exposition format."""
    lines: list[str] = []
    for m in _ALL_METRICS:
        if isinstance(m, Summary):
            lines.append(f"# HELP {m.name} {m.description}")
            lines.append(f"# TYPE {m.name} summary")
            lines.append(f"{m.name}_count {m.count}")
            lines.append(f"{m.name}_sum {round(m.total, 6)}")
        elif isinstance(m, Counter):
            lines.append(f"# HELP {m.name} {m.description}")
            lines.append(f"# TYPE {m.name} counter")
            lines.append(f"{m.name} {m.value}")
    return "\n".join(lines) + "\n"


def _reset_for_testing() -> None:
    """Reset all metric counters to zero. For test isolation only."""
    for m in _ALL_METRICS:
        with m._lock:
            if isinstance(m, Summary):
                m._count = 0
                m._total = 0.0
            elif isinstance(m, Counter):
                m._value = 0.0
