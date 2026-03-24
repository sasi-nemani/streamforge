"""
streamforge/roi.py — ROI metrics calculation for the `streamforge roi` CLI command.

Answers the question: "What engineering time did StreamForge save us this month?"
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import DriftIncidentStatus, DriftState

logger = logging.getLogger(__name__)

# Cost multiplier: Tier 2 = 25% of Tier 3 cost
TIER2_COST_FRACTION = 0.25


def parse_since(since_str: str) -> int:
    """
    Parse a 'since' string like '30d', '7d', '90d' into an integer number of days.
    Returns 30 (default) on invalid input.
    """
    try:
        s = since_str.strip().lower()
        if s.endswith("d") and s[:-1].isdigit():
            return int(s[:-1])
    except Exception:
        pass
    logger.debug("Could not parse since='%s', defaulting to 30 days", since_str)
    return 30


def compute_roi_metrics(
    state: DriftState,
    since_days: int = 30,
    tier3_cost_hours: float = 4.0,
) -> dict[str, Any]:
    """
    Compute ROI metrics from a DriftState.

    Returns a dict with:
      - total:                 int   — incidents in window
      - tier3_count:           int
      - tier2_count:           int
      - tier1_count:           int
      - estimated_hours_saved: float — engineer-hours saved
      - mttr_hours:            float | None — avg resolution time for RESOLVED incidents
      - avg_detect_minutes:    float | None — placeholder (always None in MVP)
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=since_days)

    # Filter incidents by window
    window_incidents = []
    for inc in state.incidents:
        try:
            first_dt = datetime.fromisoformat(inc.first_detected)
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=UTC)
            if first_dt >= cutoff:
                window_incidents.append((inc, first_dt))
        except Exception:
            logger.debug("Skipping incident with unparseable first_detected: %s", inc.id)

    tier3 = [(inc, dt) for inc, dt in window_incidents if inc.tier == 3]
    tier2 = [(inc, dt) for inc, dt in window_incidents if inc.tier == 2]
    tier1 = [(inc, dt) for inc, dt in window_incidents if inc.tier == 1]

    tier2_cost = tier3_cost_hours * TIER2_COST_FRACTION
    estimated_hours_saved = len(tier3) * tier3_cost_hours + len(tier2) * tier2_cost

    # MTTR: only from RESOLVED incidents in the window
    resolved = [
        (inc, dt) for inc, dt in window_incidents
        if inc.status == DriftIncidentStatus.RESOLVED and inc.last_seen
    ]
    mttr_hours: float | None = None
    if resolved:
        durations = []
        for inc, first_dt in resolved:
            try:
                last_dt = datetime.fromisoformat(inc.last_seen)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                durations.append((last_dt - first_dt).total_seconds() / 3600.0)
            except Exception:
                pass
        if durations:
            mttr_hours = sum(durations) / len(durations)

    return {
        "total": len(window_incidents),
        "tier3_count": len(tier3),
        "tier2_count": len(tier2),
        "tier1_count": len(tier1),
        "estimated_hours_saved": estimated_hours_saved,
        "mttr_hours": mttr_hours,
        "avg_detect_minutes": None,  # not tracked in MVP — requires producer event timestamps
    }


def format_roi_panel(
    stream_name: str,
    metrics: dict[str, Any],
    since_days: int = 30,
) -> str:
    """
    Format ROI metrics as a plain text panel for Rich rendering.
    Returns a string that will be wrapped in a Rich Panel by the CLI.
    """
    total = metrics["total"]
    tier3 = metrics["tier3_count"]
    tier2 = metrics["tier2_count"]
    tier1 = metrics["tier1_count"]
    hours_saved = metrics["estimated_hours_saved"]
    mttr_hours = metrics["mttr_hours"]

    lines = [
        f"Schema changes intercepted before production: {total}",
        "",
        f"  Tier 3 — Critical (would have paged oncall):         {tier3}",
        f"  Tier 2 — Breaking (would have caused data bugs):     {tier2}",
        f"  Tier 1 — Trivial:                                    {tier1}",
        "",
    ]

    if mttr_hours is not None:
        h = int(mttr_hours)
        m = int((mttr_hours - h) * 60)
        lines.append(f"Avg resolution time (MTTR): {h}h {m}m")
    else:
        lines.append("Avg resolution time (MTTR): N/A (no resolved incidents)")

    lines += [
        "",
        f"Estimated engineer-hours saved: ~{hours_saved:.0f}h",
        "(Tier 3 @ 4h each, Tier 2 @ 1h each)",
        "─" * 49,
        "Run `streamforge status` to see open incidents.",
    ]

    return "\n".join(lines)
