"""
tests/test_roi_report.py — Phase 3: Tests for ROI report calculations and CLI command.

TDD cycle: tests written FIRST and must FAIL before implementation.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from streamforge.models import DriftIncident, DriftIncidentStatus, DriftState


# ── We import the roi calculation helpers once they exist ─────────────────────

def _make_incident(
    field_path: str,
    tier: int,
    status: DriftIncidentStatus = DriftIncidentStatus.OPEN,
    first_detected: datetime | None = None,
    last_seen: datetime | None = None,
    occurrences: int = 1,
) -> DriftIncident:
    now = datetime.now(UTC)
    first = first_detected or now - timedelta(minutes=30)
    last = last_seen or now
    return DriftIncident(
        id=f"drift-{first.strftime('%Y-%m-%d-%H%M')}-{field_path.replace('.', '_')}",
        field_path=field_path,
        drift_type="type_changed" if tier == 2 else "field_removed",
        tier=tier,
        first_detected=first.isoformat(),
        last_seen=last.isoformat(),
        occurrences=occurrences,
        status=status,
    )


def _make_state(incidents: list[DriftIncident]) -> DriftState:
    return DriftState(
        stream_name="test.stream",
        updated_at=datetime.now(UTC).isoformat(),
        incidents=incidents,
    )


# ── Import the actual compute functions ───────────────────────────────────────

def _import_roi():
    """Import roi helpers — ImportError means the module doesn't exist yet (RED)."""
    from streamforge.roi import compute_roi_metrics, parse_since
    return compute_roi_metrics, parse_since


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_mttr_calculation_from_incident_timestamps():
    """MTTR = average of (last_seen - first_detected) for RESOLVED incidents."""
    compute_roi_metrics, _ = _import_roi()

    now = datetime.now(UTC)
    # Incident 1: resolved in 2 hours
    inc1 = _make_incident(
        "amount", tier=3, status=DriftIncidentStatus.RESOLVED,
        first_detected=now - timedelta(hours=3),
        last_seen=now - timedelta(hours=1),
    )
    # Incident 2: resolved in 4 hours
    inc2 = _make_incident(
        "timestamp", tier=2, status=DriftIncidentStatus.RESOLVED,
        first_detected=now - timedelta(hours=5),
        last_seen=now - timedelta(hours=1),
    )
    state = _make_state([inc1, inc2])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    # MTTR: (2h + 4h) / 2 = 3 hours
    assert metrics["mttr_hours"] is not None
    assert abs(metrics["mttr_hours"] - 3.0) < 0.1, (
        f"Expected MTTR ~3.0h, got {metrics['mttr_hours']}"
    )


def test_mttr_is_none_when_no_resolved_incidents():
    """MTTR must be None when there are no RESOLVED incidents."""
    compute_roi_metrics, _ = _import_roi()
    state = _make_state([_make_incident("amount", tier=3, status=DriftIncidentStatus.OPEN)])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)
    assert metrics["mttr_hours"] is None


def test_cost_calculation_tier3():
    """Tier 3 cost = count * tier3_cost_hours."""
    compute_roi_metrics, _ = _import_roi()
    inc1 = _make_incident("amount", tier=3)
    inc2 = _make_incident("user_id", tier=3)
    state = _make_state([inc1, inc2])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    expected_tier3_cost = 2 * 4.0  # 2 incidents × 4h
    assert abs(metrics["estimated_hours_saved"] - expected_tier3_cost) < 0.1, (
        f"Expected tier3 cost {expected_tier3_cost}h, got {metrics['estimated_hours_saved']}"
    )


def test_cost_calculation_tier2():
    """Tier 2 cost = count * (tier3_cost_hours * 0.25)."""
    compute_roi_metrics, _ = _import_roi()
    inc1 = _make_incident("timestamp", tier=2)
    inc2 = _make_incident("currency", tier=2)
    state = _make_state([inc1, inc2])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    expected_tier2_cost = 2 * (4.0 * 0.25)  # 2 incidents × 1h
    assert abs(metrics["estimated_hours_saved"] - expected_tier2_cost) < 0.1, (
        f"Expected tier2 cost {expected_tier2_cost}h, got {metrics['estimated_hours_saved']}"
    )


def test_cost_calculation_mixed_tiers():
    """Mixed tier3 + tier2 incident costs are summed correctly."""
    compute_roi_metrics, _ = _import_roi()
    inc_t3 = _make_incident("amount", tier=3)
    inc_t2_1 = _make_incident("timestamp", tier=2)
    inc_t2_2 = _make_incident("currency", tier=2)
    state = _make_state([inc_t3, inc_t2_1, inc_t2_2])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    # 1 × 4h + 2 × 1h = 6h
    assert abs(metrics["estimated_hours_saved"] - 6.0) < 0.1


def test_roi_report_contains_incidents_intercepted():
    """Output must contain 'intercepted before production'."""
    compute_roi_metrics, _ = _import_roi()
    from streamforge.roi import format_roi_panel

    inc = _make_incident("amount", tier=3)
    state = _make_state([inc])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)
    output = format_roi_panel("test.stream", metrics, since_days=30)

    assert "intercepted" in output.lower(), (
        "ROI output must contain 'intercepted'"
    )


def test_roi_report_shows_tier_breakdown():
    """Output shows separate Tier 3 and Tier 2 counts."""
    compute_roi_metrics, _ = _import_roi()
    from streamforge.roi import format_roi_panel

    inc_t3 = _make_incident("amount", tier=3)
    inc_t2 = _make_incident("timestamp", tier=2)
    state = _make_state([inc_t3, inc_t2])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)
    output = format_roi_panel("test.stream", metrics, since_days=30)

    assert "Tier 3" in output or "tier 3" in output.lower() or "critical" in output.lower(), (
        "ROI output must show Tier 3 count"
    )
    assert "Tier 2" in output or "tier 2" in output.lower() or "breaking" in output.lower(), (
        "ROI output must show Tier 2 count"
    )


def test_roi_since_filter_works():
    """--since 30d only includes incidents from last 30 days."""
    compute_roi_metrics, parse_since = _import_roi()

    now = datetime.now(UTC)
    # Incident within window (20 days ago)
    inc_recent = _make_incident(
        "amount", tier=3,
        first_detected=now - timedelta(days=20),
    )
    # Incident outside window (45 days ago)
    inc_old = _make_incident(
        "user_id", tier=3,
        first_detected=now - timedelta(days=45),
    )
    state = _make_state([inc_recent, inc_old])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    assert metrics["tier3_count"] == 1, (
        f"Expected 1 tier3 incident in last 30 days, got {metrics['tier3_count']}"
    )


def test_parse_since_days():
    """parse_since('30d') returns 30, parse_since('7d') returns 7."""
    _, parse_since = _import_roi()
    assert parse_since("30d") == 30
    assert parse_since("7d") == 7
    assert parse_since("90d") == 90


def test_parse_since_defaults_on_invalid():
    """parse_since with invalid input returns default 30."""
    _, parse_since = _import_roi()
    assert parse_since("invalid") == 30
    assert parse_since("") == 30


def test_roi_metrics_include_total_and_tier_counts():
    """metrics dict must include total, tier3_count, tier2_count, tier1_count."""
    compute_roi_metrics, _ = _import_roi()
    state = _make_state([
        _make_incident("a", tier=3),
        _make_incident("b", tier=2),
        _make_incident("c", tier=1),
    ])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)

    assert metrics["total"] == 3
    assert metrics["tier3_count"] == 1
    assert metrics["tier2_count"] == 1
    assert metrics["tier1_count"] == 1


def test_roi_avg_time_to_detect():
    """metrics must include avg_detect_minutes (avg time from producer to detection)."""
    compute_roi_metrics, _ = _import_roi()
    # We don't have "time of change" separate from first_detected, so avg_detect_minutes
    # is optional — just verify the key is present (even if None)
    state = _make_state([_make_incident("amount", tier=3)])
    metrics = compute_roi_metrics(state, since_days=30, tier3_cost_hours=4.0)
    assert "avg_detect_minutes" in metrics
