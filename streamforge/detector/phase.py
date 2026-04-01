"""Watch phase state machine — shared between file and Kafka watch loops.

Three phases:
  LEARNING      — observe N cycles, suppress Tier-1/2 alerts. Tier-3 always fires.
  STABILIZING   — require M consecutive clean cycles before declaring stable.
                  Resets if Tier-2+ drift appears.
  STABLE        — full alerting. Tier-1/2 requires K consecutive drift cycles
                  to fire (flap suppression).

This module exists to eliminate the duplicated state machine that was previously
implemented independently in watch_stream() and _watch_kafka_async().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Phase(str, Enum):
    LEARNING = "LEARNING"
    STABILIZING = "STABILIZING"
    STABLE = "STABLE"


@dataclass
class PhaseConfig:
    """Configurable thresholds for the phase state machine."""
    warmup_cycles: int = 10
    stability_cycles: int = 3
    consecutive_drift_threshold: int = 2


@dataclass
class WatchPhase:
    """Phase state machine for watch loops.

    Usage:
        phase = WatchPhase(config=PhaseConfig(warmup_cycles=10))
        # On each poll cycle:
        action = phase.tick(drift_report, stream_name)
        # action is one of: "suppress", "alert", "clean"
    """
    config: PhaseConfig = field(default_factory=PhaseConfig)
    phase: Phase = Phase.LEARNING
    warmup_remaining: int = -1  # -1 = not initialized
    stability_clean_count: int = 0
    consecutive_drifts: int = 0
    cycle_count: int = 0

    def __post_init__(self) -> None:
        if self.warmup_remaining < 0:
            self.warmup_remaining = self.config.warmup_cycles

    def tick(
        self,
        has_drift: bool,
        highest_tier: int = 0,
        drift_count: int = 0,
        stream_name: str = "",
    ) -> str:
        """Advance the state machine by one poll cycle.

        Args:
            has_drift: Whether drift was detected this cycle.
            highest_tier: Highest drift tier (1/2/3) if has_drift.
            drift_count: Number of drift events this cycle.
            stream_name: Stream name for logging.

        Returns:
            "suppress" — drift detected but suppressed (LEARNING or flap)
            "alert"    — drift detected and should be reported
            "clean"    — no drift this cycle
            "tier3"    — Tier-3 critical, always fires regardless of phase
        """
        self.cycle_count += 1

        # Tier-3 always fires, regardless of phase
        if has_drift and highest_tier >= 3:
            if self.phase == Phase.STABLE:
                self.consecutive_drifts = 0  # critical resets flap counter
            return "tier3"

        # ── LEARNING ────────────────────────────────────────────────────
        if self.phase == Phase.LEARNING:
            self.warmup_remaining -= 1

            if self.warmup_remaining <= 0:
                self.phase = Phase.STABILIZING
                self.stability_clean_count = 0
                logger.info(
                    "%s — LEARNING complete, entering STABILIZING",
                    stream_name,
                )

            if has_drift:
                return "suppress"
            return "clean"

        # ── STABILIZING ─────────────────────────────────────────────────
        if self.phase == Phase.STABILIZING:
            if has_drift and highest_tier >= 2:
                self.stability_clean_count = 0
                return "suppress"
            elif has_drift:
                return "suppress"
            else:
                self.stability_clean_count += 1
                if self.stability_clean_count >= self.config.stability_cycles:
                    self.phase = Phase.STABLE
                    self.consecutive_drifts = 0
                    logger.info(
                        "%s — STABILIZING complete, entering STABLE",
                        stream_name,
                    )
                return "clean"

        # ── STABLE ──────────────────────────────────────────────────────
        if has_drift:
            self.consecutive_drifts += 1
            if self.consecutive_drifts >= self.config.consecutive_drift_threshold:
                return "alert"
            return "suppress"
        else:
            self.consecutive_drifts = 0
            return "clean"

    @property
    def status_line(self) -> str:
        """Human-readable status for log output."""
        if self.phase == Phase.LEARNING:
            return f"LEARNING ({self.warmup_remaining} cycle(s) remaining)"
        elif self.phase == Phase.STABILIZING:
            return (
                f"STABILIZING ({self.stability_clean_count}/"
                f"{self.config.stability_cycles} clean cycles)"
            )
        else:
            return "STABLE"
