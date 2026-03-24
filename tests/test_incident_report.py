"""Tests for the incident-report command."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from typer.testing import CliRunner
from streamforge.__main__ import app


def _make_drift_report_md(tmp_path: Path, topic: str, tier: int, field: str, drift_type: str, ts: str) -> Path:
    """Create a minimal drift report markdown file."""
    slug = topic.replace(".", "_").replace("/", "_")
    reports_dir = tmp_path / "drift_reports" / slug
    reports_dir.mkdir(parents=True, exist_ok=True)
    fname = ts.replace(":", "").replace("-", "") + ".md"
    content = f"""# Drift Report — {topic}
**Detected:** {ts}
**Schema Version:** 1.0.0
**Events Sampled:** 200
**Highest Severity:** Tier {tier}

## Drift Events (1)

### `{field}`
- **Drift type**: `{drift_type}`
- **Tier**: {tier}
"""
    path = reports_dir / fname
    path.write_text(content)
    return path


def test_incident_report_no_reports(tmp_path, monkeypatch):
    """When no drift reports exist, command exits 0 with 'no incidents' message."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["incident-report", "kafka://events.test"])
    assert result.exit_code == 0
    assert "no incidents" in result.output.lower() or "0 incidents" in result.output.lower()


def test_incident_report_shows_tier3(tmp_path, monkeypatch):
    """TIER 3 incidents appear in report."""
    monkeypatch.chdir(tmp_path)
    ts = "2026-03-20T14:30:00Z"
    _make_drift_report_md(tmp_path, "events.payments", 3, "amount", "field_removed", ts)
    runner = CliRunner()
    result = runner.invoke(app, ["incident-report", "kafka://events.payments",
                                  "--drift-reports-dir", str(tmp_path / "drift_reports")])
    assert result.exit_code == 0
    assert "amount" in result.output
    assert "Tier 3" in result.output or "TIER 3" in result.output


def test_incident_report_since_filter(tmp_path, monkeypatch):
    """--since flag filters out old reports."""
    monkeypatch.chdir(tmp_path)
    old_ts = "2026-01-01T00:00:00Z"
    recent_ts = "2026-03-22T09:15:00Z"
    _make_drift_report_md(tmp_path, "events.payments", 3, "amount", "field_removed", old_ts)
    _make_drift_report_md(tmp_path, "events.payments", 2, "created_at", "type_changed", recent_ts)
    runner = CliRunner()
    result = runner.invoke(app, ["incident-report", "kafka://events.payments",
                                  "--drift-reports-dir", str(tmp_path / "drift_reports"),
                                  "--since", "7d"])
    assert result.exit_code == 0
    assert "created_at" in result.output
    # old incident filtered out
    assert "2026-01-01" not in result.output


def test_incident_report_min_tier_filter(tmp_path, monkeypatch):
    """--min-tier flag filters by minimum tier."""
    monkeypatch.chdir(tmp_path)
    ts1 = "2026-03-20T14:30:00Z"
    ts2 = "2026-03-21T10:00:00Z"
    _make_drift_report_md(tmp_path, "events.payments", 1, "new_field", "field_added", ts1)
    _make_drift_report_md(tmp_path, "events.payments", 3, "amount", "field_removed", ts2)
    runner = CliRunner()
    result = runner.invoke(app, ["incident-report", "kafka://events.payments",
                                  "--drift-reports-dir", str(tmp_path / "drift_reports"),
                                  "--min-tier", "3"])
    assert result.exit_code == 0
    assert "amount" in result.output
    # tier 1 filtered
    assert "new_field" not in result.output


def test_incident_report_output_format(tmp_path, monkeypatch):
    """Output is structured and readable — contains count, topic name, timestamps."""
    monkeypatch.chdir(tmp_path)
    ts = "2026-03-20T14:30:00Z"
    _make_drift_report_md(tmp_path, "events.payments", 3, "amount", "field_removed", ts)
    runner = CliRunner()
    result = runner.invoke(app, ["incident-report", "kafka://events.payments",
                                  "--drift-reports-dir", str(tmp_path / "drift_reports")])
    assert result.exit_code == 0
    assert "events.payments" in result.output
    assert "2026-03-20" in result.output
