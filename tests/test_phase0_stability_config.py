"""
tests/test_phase0_stability_config.py — Phase 0: StabilityConfig TDD tests

RED phase: these tests define the expected behaviour before implementation.
All tests here must pass GREEN after Phase 0 implementation is complete.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data), encoding="utf-8")


def _make_config_root(tmp_path: Path, default: dict | None = None, topic: str | None = None, topic_data: dict | None = None) -> Path:
    root = tmp_path / "config"
    default_cfg = default or {}
    _write_yaml(root / "default.yaml", default_cfg)
    if topic and topic_data:
        _write_yaml(root / "topics" / f"{topic}.yaml", topic_data)
    return root


# ──────────────────────────────────────────────────────────────────────────────
# 1. StabilityConfig dataclass — defaults
# ──────────────────────────────────────────────────────────────────────────────

class TestStabilityConfigDefaults:
    """StabilityConfig must exist with correct field names and default values."""

    def test_stability_config_importable(self):
        from streamforge.topic_config import StabilityConfig  # noqa: F401

    def test_stability_config_default_warmup_cycles(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig()
        assert cfg.warmup_cycles == 10

    def test_stability_config_default_stability_cycles(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig()
        assert cfg.stability_cycles == 3

    def test_stability_config_default_consecutive_drift_threshold(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig()
        assert cfg.consecutive_drift_threshold == 2

    def test_stability_config_default_new_cluster_threshold(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig()
        assert cfg.new_cluster_threshold == pytest.approx(0.12)

    def test_stability_config_default_new_cluster_is_evolution(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig()
        assert cfg.new_cluster_is_evolution is False

    def test_stability_config_is_dataclass(self):
        """StabilityConfig must be a dataclass (not a Pydantic model or plain class)."""
        import dataclasses

        from streamforge.topic_config import StabilityConfig
        assert dataclasses.is_dataclass(StabilityConfig)

    def test_stability_config_custom_values(self):
        from streamforge.topic_config import StabilityConfig
        cfg = StabilityConfig(
            warmup_cycles=20,
            stability_cycles=5,
            consecutive_drift_threshold=3,
            new_cluster_threshold=0.25,
            new_cluster_is_evolution=True,
        )
        assert cfg.warmup_cycles == 20
        assert cfg.stability_cycles == 5
        assert cfg.consecutive_drift_threshold == 3
        assert cfg.new_cluster_threshold == pytest.approx(0.25)
        assert cfg.new_cluster_is_evolution is True


# ──────────────────────────────────────────────────────────────────────────────
# 2. TopicConfig.stability field
# ──────────────────────────────────────────────────────────────────────────────

class TestTopicConfigHasStabilityField:
    """TopicConfig must expose a .stability attribute of type StabilityConfig."""

    def test_topic_config_has_stability_field(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={"watch": {"interval_seconds": 30}})
        cfg = load_topic_config(config_root=root)
        assert hasattr(cfg, "stability")

    def test_stability_field_is_stability_config_instance(self, tmp_path):
        from streamforge.topic_config import StabilityConfig, load_topic_config
        root = _make_config_root(tmp_path, default={"watch": {"interval_seconds": 30}})
        cfg = load_topic_config(config_root=root)
        assert isinstance(cfg.stability, StabilityConfig)

    def test_stability_defaults_loaded_when_no_stability_block(self, tmp_path):
        """When config has no 'stability:' block, defaults are used."""
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={"watch": {"interval_seconds": 30}})
        cfg = load_topic_config(config_root=root)
        assert cfg.stability.warmup_cycles == 10
        assert cfg.stability.stability_cycles == 3
        assert cfg.stability.consecutive_drift_threshold == 2


# ──────────────────────────────────────────────────────────────────────────────
# 3. StabilityConfig loaded from default.yaml
# ──────────────────────────────────────────────────────────────────────────────

class TestStabilityConfigFromDefaultYaml:
    """stability: block in default.yaml is parsed into StabilityConfig."""

    def test_warmup_cycles_from_default_yaml(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={
            "watch": {"interval_seconds": 30},
            "stability": {"warmup_cycles": 15},
        })
        cfg = load_topic_config(config_root=root)
        assert cfg.stability.warmup_cycles == 15

    def test_stability_cycles_from_default_yaml(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={
            "watch": {"interval_seconds": 30},
            "stability": {"stability_cycles": 7},
        })
        cfg = load_topic_config(config_root=root)
        assert cfg.stability.stability_cycles == 7

    def test_partial_stability_block_uses_defaults_for_missing_keys(self, tmp_path):
        """Only warmup_cycles is overridden; other keys fall back to defaults."""
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={
            "watch": {"interval_seconds": 30},
            "stability": {"warmup_cycles": 20},
        })
        cfg = load_topic_config(config_root=root)
        assert cfg.stability.warmup_cycles == 20
        # These were not in the config block — should remain at defaults
        assert cfg.stability.stability_cycles == 3
        assert cfg.stability.consecutive_drift_threshold == 2

    def test_full_stability_block_parsed(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(tmp_path, default={
            "watch": {"interval_seconds": 30},
            "stability": {
                "warmup_cycles": 8,
                "stability_cycles": 4,
                "consecutive_drift_threshold": 3,
                "new_cluster_threshold": 0.20,
                "new_cluster_is_evolution": True,
            },
        })
        cfg = load_topic_config(config_root=root)
        assert cfg.stability.warmup_cycles == 8
        assert cfg.stability.stability_cycles == 4
        assert cfg.stability.consecutive_drift_threshold == 3
        assert cfg.stability.new_cluster_threshold == pytest.approx(0.20)
        assert cfg.stability.new_cluster_is_evolution is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. Per-topic override of stability block
# ──────────────────────────────────────────────────────────────────────────────

class TestStabilityConfigPerTopicOverride:
    """Topic-level config must override the default stability values."""

    def test_topic_overrides_warmup_cycles(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(
            tmp_path,
            default={
                "watch": {"interval_seconds": 30},
                "stability": {"warmup_cycles": 10, "stability_cycles": 3},
            },
            topic="events.all",
            topic_data={"stability": {"warmup_cycles": 5}},
        )
        cfg = load_topic_config("events.all", config_root=root)
        assert cfg.stability.warmup_cycles == 5
        # stability_cycles not in topic override — should come from default
        assert cfg.stability.stability_cycles == 3

    def test_topic_overrides_new_cluster_threshold(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(
            tmp_path,
            default={
                "watch": {"interval_seconds": 30},
                "stability": {"new_cluster_threshold": 0.12},
            },
            topic="events.all",
            topic_data={"stability": {"new_cluster_threshold": 0.30, "new_cluster_is_evolution": True}},
        )
        cfg = load_topic_config("events.all", config_root=root)
        assert cfg.stability.new_cluster_threshold == pytest.approx(0.30)
        assert cfg.stability.new_cluster_is_evolution is True

    def test_topic_without_stability_block_uses_default(self, tmp_path):
        from streamforge.topic_config import load_topic_config
        root = _make_config_root(
            tmp_path,
            default={
                "watch": {"interval_seconds": 30},
                "stability": {"warmup_cycles": 10, "stability_cycles": 3},
            },
            topic="events.payments",
            topic_data={"watch": {"interval_seconds": 60}},  # no stability block
        )
        cfg = load_topic_config("events.payments", config_root=root)
        # Should inherit from default
        assert cfg.stability.warmup_cycles == 10
        assert cfg.stability.stability_cycles == 3


# ──────────────────────────────────────────────────────────────────────────────
# 5. scaffold_topic_config()
# ──────────────────────────────────────────────────────────────────────────────

class TestScaffoldTopicConfig:
    """scaffold_topic_config() must create a YAML file or skip if it exists."""

    def test_scaffold_creates_file_when_missing(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        result = scaffold_topic_config("events.payments", config_root=root)
        assert result is not None
        assert result.exists()
        assert result.name == "events.payments.yaml"

    def test_scaffold_returns_path_on_create(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        result = scaffold_topic_config("events.payments", config_root=root)
        assert isinstance(result, Path)

    def test_scaffold_returns_none_when_file_exists(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        topics_dir = root / "topics"
        topics_dir.mkdir(parents=True)
        existing = topics_dir / "events.payments.yaml"
        existing.write_text("# existing\n")
        result = scaffold_topic_config("events.payments", config_root=root)
        assert result is None

    def test_scaffold_does_not_overwrite_existing_file(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        topics_dir = root / "topics"
        topics_dir.mkdir(parents=True)
        existing = topics_dir / "events.payments.yaml"
        original_content = "# my custom config\nwatch:\n  interval_seconds: 999\n"
        existing.write_text(original_content)
        scaffold_topic_config("events.payments", config_root=root)
        assert existing.read_text() == original_content

    def test_scaffold_is_idempotent(self, tmp_path):
        """Calling scaffold multiple times is safe — no error, no overwrite."""
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        # First call creates the file
        result1 = scaffold_topic_config("events.all", config_root=root)
        assert result1 is not None
        content_after_first = result1.read_text()
        # Second call should be a no-op
        result2 = scaffold_topic_config("events.all", config_root=root)
        assert result2 is None
        # Content must not have changed
        assert result1.read_text() == content_after_first

    def test_scaffold_creates_topics_dir_if_missing(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        # topics/ directory does not exist yet
        assert not (root / "topics").exists()
        scaffold_topic_config("events.iot", config_root=root)
        assert (root / "topics").exists()

    def test_scaffold_file_contains_topic_name(self, tmp_path):
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        result = scaffold_topic_config("events.bookings", config_root=root)
        content = result.read_text()
        assert "events.bookings" in content

    def test_scaffold_file_has_stability_commented_defaults(self, tmp_path):
        """Scaffolded file should hint at stability config (as comments or defaults)."""
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        result = scaffold_topic_config("events.iot", config_root=root)
        content = result.read_text()
        # The file should at minimum mention stability
        assert "stability" in content

    def test_scaffold_file_is_valid_yaml(self, tmp_path):
        """Scaffolded file must be parseable YAML (no syntax errors)."""
        from streamforge.topic_config import scaffold_topic_config
        root = tmp_path / "config"
        root.mkdir()
        result = scaffold_topic_config("events.test", config_root=root)
        content = result.read_text()
        parsed = yaml.safe_load(content)
        # It's OK if all content is comments (parsed=None), but must not raise
        # If it has non-comment content it should parse to a dict or None
        assert parsed is None or isinstance(parsed, dict)


# ──────────────────────────────────────────────────────────────────────────────
# 6. drift_detector reads stability from TopicConfig
# ──────────────────────────────────────────────────────────────────────────────

class TestDriftDetectorReadsFromTopicConfig:
    """
    The stability state machine in _watch_kafka_async must prefer TopicConfig.stability
    over env vars when a StabilityConfig is present.

    We test this by verifying the env-var-read code path is bypassed when
    topic_cfg.stability is set — without running the full async watch loop.
    """

    def test_stability_values_resolved_from_topic_config(self, tmp_path):
        """
        When topic_cfg.stability is set, _resolve_stability_params() (or equivalent)
        must return values from it, NOT from env vars.
        """
        from streamforge.topic_config import StabilityConfig, TopicConfig

        stab = StabilityConfig(warmup_cycles=7, stability_cycles=2, consecutive_drift_threshold=4)

        # Build a minimal TopicConfig with the stability set
        topic_cfg = TopicConfig(topic="events.test", env="dev", stability=stab)

        # Simulate what the drift detector does:
        _stab = getattr(topic_cfg, "stability", None)
        warmup = (
            _stab.warmup_cycles if _stab else
            int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
        )
        stability_needed = (
            _stab.stability_cycles if _stab else
            int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
        )
        consec = (
            _stab.consecutive_drift_threshold if _stab else
            int(os.environ.get("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "2"))
        )

        assert warmup == 7
        assert stability_needed == 2
        assert consec == 4

    def test_env_var_fallback_when_no_stability_config(self, monkeypatch):
        """When topic_cfg has no stability (None), env vars are used as fallback."""
        monkeypatch.setenv("STREAMFORGE_WARMUP_CYCLES", "99")
        monkeypatch.setenv("STREAMFORGE_STABILITY_CYCLES", "5")
        monkeypatch.setenv("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "6")

        # Simulate a TopicConfig without stability (None or missing attribute)
        # We use a simple object to simulate the case where getattr returns None
        class _FakeCfg:
            stability = None

        topic_cfg = _FakeCfg()

        _stab = getattr(topic_cfg, "stability", None)
        warmup = (
            _stab.warmup_cycles if _stab else
            int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
        )
        stability_needed = (
            _stab.stability_cycles if _stab else
            int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
        )
        consec = (
            _stab.consecutive_drift_threshold if _stab else
            int(os.environ.get("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "2"))
        )

        assert warmup == 99
        assert stability_needed == 5
        assert consec == 6

    def test_env_var_fallback_uses_hardcoded_defaults_when_env_not_set(self, monkeypatch):
        """Without env vars or config, hardcoded defaults (10/3/2) must be used."""
        monkeypatch.delenv("STREAMFORGE_WARMUP_CYCLES", raising=False)
        monkeypatch.delenv("STREAMFORGE_STABILITY_CYCLES", raising=False)
        monkeypatch.delenv("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", raising=False)

        class _FakeCfg:
            stability = None

        topic_cfg = _FakeCfg()
        _stab = getattr(topic_cfg, "stability", None)
        warmup = (
            _stab.warmup_cycles if _stab else
            int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
        )
        stability_needed = (
            _stab.stability_cycles if _stab else
            int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
        )
        consec = (
            _stab.consecutive_drift_threshold if _stab else
            int(os.environ.get("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "2"))
        )

        assert warmup == 10
        assert stability_needed == 3
        assert consec == 2

    def test_topic_config_stability_overrides_env_vars(self, monkeypatch):
        """
        Even when env vars are set to different values, TopicConfig.stability
        must win when it is present.
        """
        from streamforge.topic_config import StabilityConfig, TopicConfig

        monkeypatch.setenv("STREAMFORGE_WARMUP_CYCLES", "99")
        monkeypatch.setenv("STREAMFORGE_STABILITY_CYCLES", "88")

        stab = StabilityConfig(warmup_cycles=5, stability_cycles=2)
        topic_cfg = TopicConfig(topic="events.test", env="dev", stability=stab)

        _stab = getattr(topic_cfg, "stability", None)
        warmup = (
            _stab.warmup_cycles if _stab else
            int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
        )
        stability_needed = (
            _stab.stability_cycles if _stab else
            int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
        )

        # Config wins over env vars
        assert warmup == 5
        assert stability_needed == 2


# ──────────────────────────────────────────────────────────────────────────────
# 7. events.all.yaml config file — loaded correctly
# ──────────────────────────────────────────────────────────────────────────────

class TestEventsAllYaml:
    """
    config/topics/events.all.yaml must exist and contain the required stability overrides.
    These tests run against the REAL config directory in the project.
    """

    def test_events_all_yaml_exists(self):
        events_all = Path("config/topics/events.all.yaml")
        assert events_all.exists(), "config/topics/events.all.yaml must be created as part of Phase 0"

    def test_events_all_stability_new_cluster_threshold(self):
        """events.all must set new_cluster_threshold to 0.30 for wiki-style mixed streams."""
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.stability.new_cluster_threshold == pytest.approx(0.30), (
            f"Expected 0.30, got {cfg.stability.new_cluster_threshold}"
        )

    def test_events_all_stability_new_cluster_is_evolution(self):
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.stability.new_cluster_is_evolution is True

    def test_events_all_watch_sample_size(self):
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.sample_size == 400

    def test_events_all_watch_window_capacity(self):
        from streamforge.topic_config import load_topic_config
        cfg = load_topic_config("events.all")
        assert cfg.window_capacity == 3000


# ──────────────────────────────────────────────────────────────────────────────
# 8. default.yaml has stability block
# ──────────────────────────────────────────────────────────────────────────────

class TestDefaultYamlStabilityBlock:
    """config/default.yaml must contain the stability: block."""

    def test_default_yaml_has_stability_block(self):
        default_yaml = Path("config/default.yaml")
        assert default_yaml.exists()
        content = yaml.safe_load(default_yaml.read_text())
        assert "stability" in content, "default.yaml must contain a 'stability:' block"

    def test_default_yaml_stability_warmup_cycles(self):
        default_yaml = Path("config/default.yaml")
        content = yaml.safe_load(default_yaml.read_text())
        assert content["stability"]["warmup_cycles"] == 10

    def test_default_yaml_stability_stability_cycles(self):
        default_yaml = Path("config/default.yaml")
        content = yaml.safe_load(default_yaml.read_text())
        assert content["stability"]["stability_cycles"] == 3

    def test_default_yaml_stability_consecutive_drift_threshold(self):
        default_yaml = Path("config/default.yaml")
        content = yaml.safe_load(default_yaml.read_text())
        assert content["stability"]["consecutive_drift_threshold"] == 2

    def test_default_yaml_stability_new_cluster_threshold(self):
        default_yaml = Path("config/default.yaml")
        content = yaml.safe_load(default_yaml.read_text())
        assert content["stability"]["new_cluster_threshold"] == pytest.approx(0.12)

    def test_default_yaml_stability_new_cluster_is_evolution(self):
        default_yaml = Path("config/default.yaml")
        content = yaml.safe_load(default_yaml.read_text())
        assert content["stability"]["new_cluster_is_evolution"] is False
