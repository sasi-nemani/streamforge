"""
Tests that load_topic_config does not mutate the module-level _CONFIG_ROOT.

These tests are in the RED phase — they FAIL until load_topic_config is refactored
to pass config_root as a parameter to _resolve_raw instead of mutating the global.
"""

from __future__ import annotations

from pathlib import Path

import streamforge.topic_config as tc_module
from streamforge.topic_config import load_topic_config

# ── helpers ────────────────────────────────────────────────────────────────────


def _write_config(directory: Path, interval_seconds: int) -> None:
    """Write a minimal default.yaml into *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "default.yaml").write_text(
        f"watch:\n  interval_seconds: {interval_seconds}\n"
    )


# ── global mutation tests ──────────────────────────────────────────────────────


class TestLoadTopicConfigDoesNotPollute:
    """load_topic_config(config_root=X) must not permanently redirect future calls."""

    def test_subsequent_call_without_config_root_uses_original_root(self, tmp_path):
        """
        After calling load_topic_config(config_root=dir_A), a subsequent call
        without config_root must NOT use dir_A — it must fall back to whatever
        _CONFIG_ROOT was before the first call.
        """
        dir_a = tmp_path / "config_a"
        dir_b = tmp_path / "config_b"
        _write_config(dir_a, interval_seconds=999)
        _write_config(dir_b, interval_seconds=111)

        # Point the module's root at dir_b (our "correct default")
        original = tc_module._CONFIG_ROOT
        tc_module._CONFIG_ROOT = dir_b
        try:
            # First call overrides root to dir_a
            load_topic_config(config_root=dir_a)

            # Second call with no override — must still use dir_b
            cfg = load_topic_config()
            assert cfg.poll_interval_seconds == 111, (
                f"Expected 111 (from dir_b), got {cfg.poll_interval_seconds} — "
                "load_topic_config(config_root=dir_a) polluted _CONFIG_ROOT"
            )
        finally:
            tc_module._CONFIG_ROOT = original

    def test_two_successive_explicit_overrides_are_independent(self, tmp_path):
        """
        Each call with an explicit config_root should use that root and not
        carry state over to the next call.
        """
        dir_a = tmp_path / "config_a"
        dir_b = tmp_path / "config_b"
        _write_config(dir_a, interval_seconds=100)
        _write_config(dir_b, interval_seconds=200)

        original = tc_module._CONFIG_ROOT
        try:
            cfg_a = load_topic_config(config_root=dir_a)
            cfg_b = load_topic_config(config_root=dir_b)

            assert cfg_a.poll_interval_seconds == 100
            assert cfg_b.poll_interval_seconds == 200
        finally:
            tc_module._CONFIG_ROOT = original

    def test_module_global_unchanged_after_call_with_explicit_root(self, tmp_path):
        """
        The module attribute _CONFIG_ROOT must not change when config_root is passed.
        """
        dir_a = tmp_path / "config_a"
        _write_config(dir_a, interval_seconds=77)

        original = tc_module._CONFIG_ROOT
        try:
            load_topic_config(config_root=dir_a)
            assert tc_module._CONFIG_ROOT is original, (
                f"_CONFIG_ROOT was mutated from {original!r} to {tc_module._CONFIG_ROOT!r}"
            )
        finally:
            tc_module._CONFIG_ROOT = original

    def test_config_root_none_uses_current_module_root(self, tmp_path):
        """
        Calling load_topic_config(config_root=None) explicitly must behave
        identically to calling load_topic_config() — using whatever _CONFIG_ROOT
        the module currently has.
        """
        dir_b = tmp_path / "config_b"
        _write_config(dir_b, interval_seconds=42)

        original = tc_module._CONFIG_ROOT
        tc_module._CONFIG_ROOT = dir_b
        try:
            cfg = load_topic_config(config_root=None)
            assert cfg.poll_interval_seconds == 42
        finally:
            tc_module._CONFIG_ROOT = original


class TestLoadTopicConfigRepeatedCalls:
    """Repeated calls with no config_root must remain stable (no accumulated drift)."""

    def test_repeated_calls_return_same_interval(self, tmp_path):
        dir_stable = tmp_path / "stable"
        _write_config(dir_stable, interval_seconds=30)

        original = tc_module._CONFIG_ROOT
        tc_module._CONFIG_ROOT = dir_stable
        try:
            intervals = [load_topic_config().poll_interval_seconds for _ in range(3)]
            assert intervals == [30, 30, 30], f"Unexpected drift across calls: {intervals}"
        finally:
            tc_module._CONFIG_ROOT = original

    def test_interleaved_explicit_and_default_calls(self, tmp_path):
        """Explicit-root calls sandwiched between default calls must not corrupt defaults."""
        dir_default = tmp_path / "default_cfg"
        dir_other = tmp_path / "other_cfg"
        _write_config(dir_default, interval_seconds=15)
        _write_config(dir_other, interval_seconds=500)

        original = tc_module._CONFIG_ROOT
        tc_module._CONFIG_ROOT = dir_default
        try:
            cfg1 = load_topic_config()                          # uses dir_default → 15
            _    = load_topic_config(config_root=dir_other)     # uses dir_other → 500
            cfg3 = load_topic_config()                          # must use dir_default → 15 again

            assert cfg1.poll_interval_seconds == 15
            assert cfg3.poll_interval_seconds == 15, (
                f"Third call returned {cfg3.poll_interval_seconds}, expected 15 — "
                "middle call with explicit config_root polluted _CONFIG_ROOT"
            )
        finally:
            tc_module._CONFIG_ROOT = original
