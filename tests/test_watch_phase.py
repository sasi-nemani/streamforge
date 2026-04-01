"""Tests for the WatchPhase state machine."""

from streamforge.detector.phase import Phase, PhaseConfig, WatchPhase


class TestWatchPhase:
    def _make(self, warmup=3, stability=2, consec=2):
        return WatchPhase(config=PhaseConfig(
            warmup_cycles=warmup,
            stability_cycles=stability,
            consecutive_drift_threshold=consec,
        ))

    def test_starts_in_learning(self):
        p = self._make()
        assert p.phase == Phase.LEARNING

    def test_learning_suppresses_tier1(self):
        p = self._make(warmup=3)
        assert p.tick(has_drift=True, highest_tier=1) == "suppress"

    def test_learning_suppresses_tier2(self):
        p = self._make(warmup=3)
        assert p.tick(has_drift=True, highest_tier=2) == "suppress"

    def test_tier3_always_fires_in_learning(self):
        p = self._make(warmup=3)
        assert p.tick(has_drift=True, highest_tier=3) == "tier3"

    def test_learning_transitions_to_stabilizing(self):
        p = self._make(warmup=2)
        p.tick(has_drift=False)  # cycle 1
        p.tick(has_drift=False)  # cycle 2 — warmup done
        assert p.phase == Phase.STABILIZING

    def test_stabilizing_resets_on_tier2(self):
        p = self._make(warmup=1, stability=3)
        p.tick(has_drift=False)  # exit LEARNING
        assert p.phase == Phase.STABILIZING
        p.tick(has_drift=False)  # clean 1/3
        p.tick(has_drift=True, highest_tier=2)  # reset
        assert p.stability_clean_count == 0

    def test_stabilizing_transitions_to_stable(self):
        p = self._make(warmup=1, stability=2)
        p.tick(has_drift=False)  # exit LEARNING
        p.tick(has_drift=False)  # clean 1/2
        p.tick(has_drift=False)  # clean 2/2 — stable
        assert p.phase == Phase.STABLE

    def test_stable_suppresses_first_drift(self):
        p = self._make(warmup=1, stability=1, consec=2)
        p.tick(has_drift=False)  # exit LEARNING
        p.tick(has_drift=False)  # exit STABILIZING
        assert p.phase == Phase.STABLE
        assert p.tick(has_drift=True, highest_tier=2) == "suppress"

    def test_stable_alerts_on_consecutive_drift(self):
        p = self._make(warmup=1, stability=1, consec=2)
        p.tick(has_drift=False)  # exit LEARNING
        p.tick(has_drift=False)  # exit STABILIZING
        p.tick(has_drift=True, highest_tier=2)  # 1st — suppress
        assert p.tick(has_drift=True, highest_tier=2) == "alert"  # 2nd — alert

    def test_stable_resets_on_clean(self):
        p = self._make(warmup=1, stability=1, consec=2)
        p.tick(has_drift=False)
        p.tick(has_drift=False)
        p.tick(has_drift=True, highest_tier=2)  # 1st
        p.tick(has_drift=False)  # clean resets counter
        assert p.consecutive_drifts == 0
        assert p.tick(has_drift=True, highest_tier=2) == "suppress"  # starts over

    def test_tier3_fires_in_stable(self):
        p = self._make(warmup=1, stability=1, consec=2)
        p.tick(has_drift=False)
        p.tick(has_drift=False)
        assert p.tick(has_drift=True, highest_tier=3) == "tier3"

    def test_status_line_learning(self):
        p = self._make(warmup=5)
        assert "LEARNING" in p.status_line
        assert "5" in p.status_line

    def test_status_line_stable(self):
        p = self._make(warmup=1, stability=1)
        p.tick(has_drift=False)
        p.tick(has_drift=False)
        assert "STABLE" in p.status_line
