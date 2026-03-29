"""Tests for the Field Type RAG Registry."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from streamforge.field_registry import (
    DEFAULT_REGISTRY_PATH,
    FieldTypeObservation,
    FieldTypeRegistry,
    RegistryConfig,
)
from streamforge.models import FieldSchema, FieldType, PIICategory


# ---------------------------------------------------------------------------
# Observation dataclass
# ---------------------------------------------------------------------------

class TestFieldTypeObservation:
    def test_to_dict_roundtrip(self):
        obs = FieldTypeObservation(
            field_path="user.email",
            field_type="email",
            confidence=0.95,
            last_seen="2026-01-15T10:00:00Z",
            stream_names=["payments"],
            observation_count=3,
            sample_values=["a@b.com"],
            pii_categories=["email"],
        )
        d = obs.to_dict()
        restored = FieldTypeObservation.from_dict(d)
        assert restored.field_path == "user.email"
        assert restored.field_type == "email"
        assert restored.confidence == 0.95
        assert restored.observation_count == 3
        assert restored.pii_categories == ["email"]

    def test_from_dict_defaults(self):
        obs = FieldTypeObservation.from_dict({"field_path": "x", "field_type": "string"})
        assert obs.observation_count == 1
        assert obs.confidence == 0.5
        assert obs.sample_values == []


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------

class TestRegistryCRUD:
    def test_record_new_field(self):
        reg = FieldTypeRegistry()
        reg.record("user.email", "email", 0.95, "payments", ["a@b.com"])
        assert "user.email" in reg
        assert len(reg) == 1

    def test_record_updates_existing(self):
        reg = FieldTypeRegistry()
        reg.record("user.email", "email", 0.90, "payments")
        reg.record("user.email", "email", 0.95, "bookings")
        obs = reg._observations["user.email"]
        assert obs.observation_count == 2
        assert obs.confidence == 0.95  # latest observation wins
        assert set(obs.stream_names) == {"payments", "bookings"}

    def test_record_uses_latest_confidence_not_max(self):
        """H4 regression: confidence must reflect the latest observation,
        not ratchet up via max(). A correct re-inference at lower confidence
        should not be overridden by an older high-confidence mistype."""
        reg = FieldTypeRegistry()
        reg.record("field", "timestamp_epoch_ms", 0.85, "s1")  # initial: wrong type
        reg.record("field", "integer", 0.70, "s2")              # corrected: right type, lower confidence
        obs = reg._observations["field"]
        assert obs.field_type == "integer"
        assert obs.confidence == 0.70  # latest, not max(0.85, 0.70)

    def test_record_from_schema(self):
        reg = FieldTypeRegistry()
        fields = [
            FieldSchema(
                name="email", path="user.email", field_type=FieldType.EMAIL,
                confidence=0.9, pii_categories=[PIICategory.EMAIL],
            ),
            FieldSchema(
                name="amount", path="amount", field_type=FieldType.FLOAT,
                confidence=0.85,
            ),
        ]
        reg.record_from_schema(fields, "payments")
        assert len(reg) == 2
        assert reg._observations["user.email"].pii_categories == ["email"]

    def test_clear_resets(self):
        reg = FieldTypeRegistry()
        reg.record("x", "string", 0.9, "s")
        reg.clear()
        assert len(reg) == 0


# ---------------------------------------------------------------------------
# Lookup logic
# ---------------------------------------------------------------------------

class TestLookup:
    def _make_registry(self) -> FieldTypeRegistry:
        reg = FieldTypeRegistry()
        for i in range(4):
            reg.record("user.email", "email", 0.95, f"stream_{i}")
        return reg

    def test_lookup_hit(self):
        reg = self._make_registry()
        obs = reg.lookup("user.email")
        assert obs is not None
        assert obs.field_type == "email"

    def test_lookup_miss_unknown_path(self):
        reg = self._make_registry()
        assert reg.lookup("unknown.field") is None

    def test_lookup_miss_below_min_observations(self):
        reg = FieldTypeRegistry()
        reg.record("x", "string", 0.95, "s")
        # Default min_observations=3, only 1 recorded
        assert reg.lookup("x") is None

    def test_lookup_miss_below_min_confidence(self):
        reg = FieldTypeRegistry()
        for i in range(5):
            reg.record("x", "string", 0.5, f"s{i}")
        # confidence=0.5 < default 0.80
        assert reg.lookup("x") is None

    def test_lookup_respects_custom_config(self):
        reg = FieldTypeRegistry()
        reg.record("x", "string", 0.7, "s")
        reg.record("x", "string", 0.7, "s2")
        config = RegistryConfig(min_observations=2, min_confidence=0.6)
        assert reg.lookup("x", config=config) is not None

    def test_lookup_expired_observation(self):
        reg = FieldTypeRegistry()
        old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        reg._observations["old"] = FieldTypeObservation(
            field_path="old", field_type="string", confidence=0.95,
            last_seen=old_date, stream_names=["s"], observation_count=5,
        )
        # Default max_age_days=90, observation is 100 days old
        assert reg.lookup("old") is None


class TestBatchLookup:
    def test_batch_splits_cached_and_unknown(self):
        reg = FieldTypeRegistry()
        for i in range(4):
            reg.record("known", "string", 0.95, f"s{i}")
        cached, unknown = reg.lookup_batch(["known", "new_field"])
        assert "known" in cached
        assert "new_field" in unknown
        assert len(cached) == 1
        assert len(unknown) == 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        path = tmp_path / "registry.json"
        reg = FieldTypeRegistry()
        for i in range(3):
            reg.record("user.email", "email", 0.95, f"stream_{i}", ["a@b.com"])
        reg.save(path)

        loaded = FieldTypeRegistry.load(path)
        assert len(loaded) == 1
        obs = loaded._observations["user.email"]
        assert obs.observation_count == 3
        assert obs.confidence == 0.95

    def test_load_missing_file_seeds(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        reg = FieldTypeRegistry.load(path, seed=True)
        assert len(reg) > 0  # seeded with common patterns
        assert "event_id" in reg

    def test_load_missing_file_no_seed(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        reg = FieldTypeRegistry.load(path, seed=False)
        assert len(reg) == 0

    def test_load_corrupted_file(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        reg = FieldTypeRegistry.load(path)
        # Should not crash, starts fresh
        assert isinstance(reg, FieldTypeRegistry)


# ---------------------------------------------------------------------------
# to_field_schema conversion
# ---------------------------------------------------------------------------

class TestToFieldSchema:
    def test_converts_observation_to_field_schema(self):
        reg = FieldTypeRegistry()
        obs = FieldTypeObservation(
            field_path="user.email", field_type="email", confidence=0.90,
            last_seen="2026-01-01T00:00:00Z", stream_names=["payments"],
            observation_count=5, pii_categories=["email"],
        )
        fs = reg.to_field_schema(obs, presence_rate=0.95)
        assert fs.path == "user.email"
        assert fs.field_type == FieldType.EMAIL
        assert fs.required is True
        assert fs.presence_rate == 0.95
        assert abs(fs.confidence - 0.95) < 1e-9  # 0.90 + 0.05 boost
        assert PIICategory.EMAIL in fs.pii_categories
        assert "[registry]" in fs.notes


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_after_lookups(self):
        reg = FieldTypeRegistry()
        for i in range(4):
            reg.record("x", "string", 0.95, f"s{i}")
        reg.lookup("x")  # hit
        reg.lookup("y")  # miss
        s = reg.stats()
        assert s["total_entries"] == 1
        assert s["lookup_hits"] == 1
        assert s["lookup_misses"] == 1
        assert s["hit_rate"] == 0.5
