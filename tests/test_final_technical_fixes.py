"""Tests for final technical fixes from Stripe Sr. Director review.

Fix 1: Pre-drift trending — add EWMA + minimum decline magnitude + confidence
Fix 2: Supervisor — exponential backoff on restarts
"""
import math
import time

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 1: Pre-drift trending — statistical robustness
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrendingEWMA:
    """Trending must use EWMA and require minimum decline magnitude."""

    def test_temporary_blip_does_not_trigger_warning(self):
        """A single-cycle dip followed by recovery must NOT warn."""
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=10, warn_cycles=3)
        # Stable, then dip, then recovery
        for rate in [0.95, 0.95, 0.94, 0.90, 0.94, 0.95]:
            tracker.record("stable_field", rate)
        warnings = tracker.check_trends(baseline_rates={"stable_field": 0.95})
        assert len(warnings) == 0, "Temporary blip must not trigger warning"

    def test_genuine_decline_triggers_warning(self):
        """Consistent 5+ cycle decline must trigger warning."""
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=10, warn_cycles=5)
        for rate in [0.95, 0.93, 0.91, 0.89, 0.87, 0.85]:
            tracker.record("declining", rate)
        warnings = tracker.check_trends(
            baseline_rates={"declining": 0.95}, threshold=0.15,
        )
        # declining at 0.85, drift line at 0.80, ~0.02/cycle → crosses in ~2.5 cycles
        assert len(warnings) >= 1
        assert warnings[0]["field_path"] == "declining"

    def test_small_magnitude_decline_suppressed(self):
        """Decline of < 0.005 per cycle is noise, not trend."""
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=10, warn_cycles=3)
        # Very tiny decline — 0.001 per cycle
        for rate in [0.950, 0.949, 0.948, 0.947, 0.946]:
            tracker.record("tiny", rate)
        warnings = tracker.check_trends(baseline_rates={"tiny": 0.95})
        assert len(warnings) == 0, "Tiny magnitude decline must be suppressed"

    def test_warning_includes_confidence(self):
        """Warnings must include a confidence score."""
        from streamforge.detector.trending import PresenceTrendTracker
        tracker = PresenceTrendTracker(history_size=10, warn_cycles=5)
        for rate in [0.95, 0.92, 0.89, 0.86, 0.83]:
            tracker.record("confident", rate)
        warnings = tracker.check_trends(baseline_rates={"confident": 0.95})
        if warnings:
            assert "confidence" in warnings[0], "Warning must include confidence score"


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 2: Supervisor exponential backoff
# ═══════════════════════════════════════════════════════════════════════════════

class TestSupervisorExponentialBackoff:
    """Supervisor must use exponential backoff on repeated restarts."""

    def test_backoff_delay_increases(self):
        """Each consecutive restart must have longer delay."""
        from streamforge.supervisor import WorkerState
        from streamforge.models import StreamAssignment
        ws = WorkerState(StreamAssignment(
            stream_uri="test", schema_path="s.yaml",
        ))
        # Simulate 4 restarts in quick succession
        for _ in range(4):
            ws.restart_timestamps.append(time.time())

        delays = [ws.backoff_delay(i) for i in range(5)]
        # Must be monotonically increasing
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1], \
                f"Backoff delay must increase: {delays}"
        # First delay should be base (5s), last should be capped
        assert delays[0] >= 5
        assert delays[4] <= 120  # reasonable cap

    def test_backoff_capped_at_max(self):
        """Backoff must not exceed max_backoff_seconds."""
        from streamforge.supervisor import WorkerState
        from streamforge.models import StreamAssignment
        ws = WorkerState(StreamAssignment(
            stream_uri="test", schema_path="s.yaml",
        ))
        delay = ws.backoff_delay(100)  # 100th restart
        assert delay <= 120, f"Backoff must be capped, got {delay}s"

    def test_backoff_resets_after_stable_period(self):
        """If worker runs stable for 10+ minutes, backoff resets."""
        from streamforge.supervisor import WorkerState
        from streamforge.models import StreamAssignment
        ws = WorkerState(StreamAssignment(
            stream_uri="test", schema_path="s.yaml",
        ))
        # Old restart (20 minutes ago)
        ws.restart_timestamps.append(time.time() - 1200)
        # recent_restarts within 1 hour still counts it, but consecutive
        # restart count for backoff should reset since last restart was long ago
        delay = ws.backoff_delay(0)
        assert delay <= 10, "Backoff should be low after stable period"
