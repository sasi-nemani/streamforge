"""Pre-drift trending -- detects fields trending toward drift before they cross thresholds.

Pattern: Temporal analysis. If a field's presence rate has been declining for N
consecutive cycles, project when it will cross the drift threshold and warn early.
This gives operators 3-10 cycles of lead time to investigate before a Tier-2/3 alert fires.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PresenceTrendTracker:
    """Tracks per-field presence rate history for trend detection.

    Stores the last N presence rates per field. When a field shows a consistent
    downward trend that will cross the drift threshold within `warn_cycles`,
    emits a pre-drift warning.
    """

    def __init__(self, history_size: int = 10, warn_cycles: int = 3) -> None:
        self._history: dict[str, list[float]] = {}
        self._history_size = history_size
        self._warn_cycles = warn_cycles

    def record(self, field_path: str, presence_rate: float) -> None:
        """Record a new presence rate observation for a field."""
        if field_path not in self._history:
            self._history[field_path] = []
        hist = self._history[field_path]
        hist.append(presence_rate)
        if len(hist) > self._history_size:
            hist.pop(0)

    def check_trends(self, baseline_rates: dict[str, float], threshold: float = 0.15) -> list[dict[str, Any]]:
        """Check all tracked fields for downward trends.

        Returns list of warnings for fields trending toward drift.
        Each warning has: field_path, current_rate, projected_rate, cycles_to_threshold.
        """
        warnings: list[dict[str, Any]] = []
        for field_path, history in self._history.items():
            if len(history) < 3:
                continue  # need at least 3 data points

            baseline = baseline_rates.get(field_path, 1.0)

            # Simple linear trend: average of last 3 deltas
            deltas = [history[i] - history[i - 1] for i in range(1, len(history))]
            recent_deltas = deltas[-3:]

            # All recent deltas must be negative (consistent decline)
            if not all(d < 0 for d in recent_deltas):
                continue

            avg_delta = sum(recent_deltas) / len(recent_deltas)
            current = history[-1]

            # Minimum magnitude filter: decline of < 0.005/cycle is noise
            if abs(avg_delta) < 0.005:
                continue

            # Confidence: ratio of negative deltas across ALL history (not just last 3)
            all_negative = sum(1 for d in deltas if d < 0)
            confidence = round(all_negative / len(deltas), 2) if deltas else 0.0

            # threshold is relative: field drifts when presence drops by threshold from baseline
            drift_line = baseline - threshold

            if current <= drift_line:
                continue  # already past threshold, normal drift detection handles this

            remaining = current - drift_line
            if avg_delta == 0:
                continue
            cycles_to_cross = remaining / abs(avg_delta)

            if cycles_to_cross <= self._warn_cycles:
                projected = current + (avg_delta * self._warn_cycles)
                warnings.append({
                    "field_path": field_path,
                    "current_rate": round(current, 4),
                    "baseline_rate": round(baseline, 4),
                    "projected_rate": round(max(projected, 0), 4),
                    "cycles_to_threshold": round(cycles_to_cross, 1),
                    "trend": "declining",
                    "avg_delta_per_cycle": round(avg_delta, 4),
                    "confidence": confidence,
                })
                logger.warning(
                    "Pre-drift warning: field '%s' trending toward drift "
                    "(%.1f%% -> projected %.1f%% in %d cycles)",
                    field_path, current * 100, max(projected, 0) * 100,
                    int(cycles_to_cross),
                )

        return warnings

    def save(self, path: Path) -> None:
        """Persist trend history to JSON."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._history, indent=2))
        except OSError as e:
            logger.warning("Failed to save trend history: %s", e)

    @staticmethod
    def load(path: Path) -> "PresenceTrendTracker":
        """Load trend history from JSON."""
        tracker = PresenceTrendTracker()
        if path.exists():
            try:
                tracker._history = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return tracker
