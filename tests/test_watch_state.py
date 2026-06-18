"""Tests for WatchState persistence and phase transitions."""
import json

from streamforge.watch_state import WatchState, _slug


def test_slug_sanitization():
    assert _slug("events.all") == "events_all"
    assert _slug("events/payments") == "events_payments"
    assert _slug("my-topic_123") == "my-topic_123"


def test_save_and_load_roundtrip(tmp_path):
    state = WatchState(topic="events.test", cycle_count=5, warmup_done=True, phase="STABLE")
    state.save(state_dir=tmp_path)
    loaded = WatchState.load("events.test", state_dir=tmp_path)
    assert loaded.topic == "events.test"
    assert loaded.cycle_count == 5
    assert loaded.warmup_done is True
    assert loaded.phase == "STABLE"


def test_load_missing_file_returns_defaults(tmp_path):
    state = WatchState.load("events.missing", state_dir=tmp_path)
    assert state.topic == "events.missing"
    assert state.phase == "LEARNING"
    assert state.cycle_count == 0
    assert state.warmup_done is False


def test_load_corrupted_file_returns_defaults(tmp_path):
    path = tmp_path / "events_corrupt.json"
    path.write_text("this is not json {{{{")
    state = WatchState.load("events.corrupt", state_dir=tmp_path)
    assert state.topic == "events.corrupt"
    assert state.phase == "LEARNING"


def test_state_dir_created_if_missing(tmp_path):
    nested = tmp_path / "deep" / "nested" / "state"
    state = WatchState(topic="events.new")
    state.save(state_dir=nested)
    assert (nested / "events_new.json").exists()


def test_mark_drift_increments_counter():
    state = WatchState(topic="events.test", phase="STABLE")
    state.mark_drift()
    assert state.consecutive_drifts == 1
    assert state.stability_clean_count == 0
    assert state.last_drift_at is not None


def test_mark_clean_transitions_to_stable():
    state = WatchState(topic="events.test", phase="STABILIZING", stability_clean_count=2)
    result = state.mark_clean(stability_cycles_required=3)
    assert result is True
    assert state.phase == "STABLE"
    assert state.stable_since is not None


def test_mark_clean_not_yet_stable():
    state = WatchState(topic="events.test", phase="STABILIZING", stability_clean_count=1)
    result = state.mark_clean(stability_cycles_required=3)
    assert result is False
    assert state.phase == "STABILIZING"


def test_tick_warmup_transitions_to_stabilizing():
    state = WatchState(topic="events.test", warmup_remaining=1)
    state.tick_warmup(warmup_cycles=10)
    assert state.warmup_done is True
    assert state.phase == "STABILIZING"
    assert state.warmup_remaining == 0


def test_migrate_legacy(tmp_path):
    legacy = tmp_path / ".watch_state.json"
    legacy.write_text(json.dumps({"cycle_count": 10, "warmup_done": True, "phase": "STABLE"}))
    new_state_dir = tmp_path / "state"
    state = WatchState.migrate_legacy("events.old", legacy_path=legacy, state_dir=new_state_dir)
    assert state is not None
    assert state.cycle_count == 10
    assert not legacy.exists()
    assert (new_state_dir / "events_old.json").exists()
