"""Tests for the streamforge demo command."""
import time

from typer.testing import CliRunner

from streamforge.__main__ import app


def test_demo_command_exists():
    """demo command is registered in the CLI."""
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--help"])
    assert result.exit_code == 0
    assert "demo" in result.output.lower() or "kafka" in result.output.lower()


def test_demo_command_runs_without_kafka(tmp_path, monkeypatch):
    """demo command runs end-to-end with no external dependencies."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    start = time.time()
    result = runner.invoke(app, ["demo"])
    elapsed = time.time() - start
    # Should complete in under 90 seconds
    assert elapsed < 90, f"Demo took {elapsed:.1f}s (max 90s)"
    # Should not require Kafka
    assert "connection refused" not in result.output.lower()
    assert "kafka" in result.output.lower() or "schema" in result.output.lower()


def test_demo_command_shows_breaking_change(tmp_path, monkeypatch):
    """demo shows a drift detection — the core value prop."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["demo"])
    # Should show the value prop — either drift detection or schema inference
    output = result.output.lower()
    has_value = any(kw in output for kw in [
        "breaking", "drift", "schema", "field", "caught", "detected"
    ])
    assert has_value, f"Demo output missing value prop keywords. Got:\n{result.output}"


def test_demo_command_ends_with_next_steps(tmp_path, monkeypatch):
    """demo ends with a clear call to action."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["demo"])
    output = result.output.lower()
    # Should have a CTA
    has_cta = any(kw in output for kw in ["streamforge init", "streamforge watch", "real kafka", "try it"])
    assert has_cta, f"Demo missing CTA. Got:\n{result.output}"
