"""
streamforge.history.velocity — Per-field trend computation
============================================================

Compute velocity trends across all snapshots for a stream.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..models import FieldVelocity, TrendStatus, VelocityReport
from .diff import _flatten_profile
from .snapshot import list_snapshots, load_snapshot_profile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable constants — override via environment variables in production
# ---------------------------------------------------------------------------

MIN_SNAPSHOTS_FOR_TREND: int = int(os.environ.get("SF_HISTORY_MIN_SNAPSHOTS", "3"))
REMOVAL_THRESHOLD: float = float(os.environ.get("SF_HISTORY_REMOVAL_THRESHOLD", "0.20"))
ENUM_GROWTH_ALERT_RATE: float = float(os.environ.get("SF_HISTORY_ENUM_ALERT_RATE", "1.0"))
DECLINING_SLOPE_THRESHOLD: float = -0.002   # presence_rate/day (approx 6%/month for weekly snapshots)
VOLATILE_STD_THRESHOLD: float = 0.10        # stddev of presence_rates -> volatile


def _compute_trend(
    dates: list[str],
    presence_rates: list[float],
) -> tuple[TrendStatus, float | None]:
    """
    Compute trend direction and linear regression slope (presence_rate per day).

    Returns (TrendStatus, slope_per_day) or (INSUFFICIENT_DATA, None) if too few points.
    Uses least-squares linear regression so short runs with a clear direction
    report the right trend without being fooled by a single outlier.
    """
    n = len(presence_rates)
    if n < MIN_SNAPSHOTS_FOR_TREND:
        return TrendStatus.INSUFFICIENT_DATA, None

    # Convert dates to days-since-first (x axis)
    try:
        base = datetime.strptime(dates[0], "%Y-%m-%d")
        xs = [(datetime.strptime(d, "%Y-%m-%d") - base).days for d in dates]
    except ValueError:
        xs = list(range(n))

    # Least-squares slope
    ys = presence_rates
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ss_xy = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
    slope = (ss_xy / ss_xx) if ss_xx > 0 else 0.0

    # Residual stddev
    fitted = [y_mean + slope * (xs[i] - x_mean) for i in range(n)]
    residuals = [ys[i] - fitted[i] for i in range(n)]
    std = math.sqrt(sum(r ** 2 for r in residuals) / n)

    if std > VOLATILE_STD_THRESHOLD:
        return TrendStatus.VOLATILE, round(slope, 6)
    if slope > abs(DECLINING_SLOPE_THRESHOLD):
        return TrendStatus.RISING, round(slope, 6)
    if slope < DECLINING_SLOPE_THRESHOLD:
        return TrendStatus.DECLINING, round(slope, 6)
    return TrendStatus.STABLE, round(slope, 6)


def _compute_enum_growth_rate(
    series: list[tuple[str, list[str] | None]],  # [(date, enum_values_or_None)]
) -> float | None:
    """
    Return new distinct enum values per 30-day window, or None if never an enum field.
    """
    all_enums = [(d, set(v)) for d, v in series if v is not None]
    if not all_enums:
        return None
    if len(all_enums) < 2:
        return 0.0

    seen: set[str] = set(all_enums[0][1])
    new_values_total = 0
    try:
        t_start = datetime.strptime(all_enums[0][0], "%Y-%m-%d")
        t_end = datetime.strptime(all_enums[-1][0], "%Y-%m-%d")
        total_days = max((t_end - t_start).days, 1)
    except ValueError:
        total_days = len(all_enums) * 7  # assume weekly

    for _, vals in all_enums[1:]:
        new = vals - seen
        new_values_total += len(new)
        seen |= vals

    return round(new_values_total / total_days * 30, 2)


def _generate_alert(
    field_path: str,
    trend: TrendStatus,
    current_rate: float,
    slope: float | None,
    enum_growth_rate: float | None,
) -> str | None:
    """Return a human-readable alert string, or None if no alert condition met."""
    if trend == TrendStatus.DECLINING and current_rate < REMOVAL_THRESHOLD + 0.20:
        slope_str = f", slope {slope:+.4f}/day" if slope is not None else ""
        return (
            f"ALERT: `{field_path}` declining toward removal threshold "
            f"({current_rate:.0%} presence{slope_str})"
        )
    if trend == TrendStatus.DECLINING and slope is not None and slope < -0.01:
        return (
            f"ALERT: `{field_path}` presence dropping fast "
            f"({current_rate:.0%}, slope {slope:+.4f}/day)"
        )
    if trend == TrendStatus.VOLATILE and current_rate < REMOVAL_THRESHOLD + 0.15:
        return (
            f"WATCH: `{field_path}` presence unstable near removal threshold "
            f"({current_rate:.0%})"
        )
    if enum_growth_rate is not None and enum_growth_rate > ENUM_GROWTH_ALERT_RATE:
        return (
            f"ALERT: `{field_path}` enum expanding rapidly "
            f"({enum_growth_rate:.1f} new values/30 days)"
        )
    return None


def compute_velocity(output_dir: str, stream_name: str) -> VelocityReport:
    """
    Load all snapshots and compute per-field velocity trends.

    For each unique (cluster_id, field_path) across all snapshots:
    - Collect presence_rate, confidence, enum_values over time
    - Compute trend and slope via linear regression
    - Generate alert strings where thresholds are crossed

    Returns a VelocityReport (does NOT write to disk).
    """
    now = datetime.now(UTC).isoformat()
    snaps = list_snapshots(output_dir, stream_name)

    if not snaps:
        return VelocityReport(
            stream_name=stream_name,
            computed_at=now,
            snapshot_count=0,
        )

    snap_dates = [s.name for s in snaps]  # directory names are YYYY-MM-DD

    # Build time-series per (cluster_id, field_path)
    # series[key] = [(date, presence_rate, field_type, enum_values, confidence)]
    series: dict[tuple[str, str], list[tuple[str, float, str, list[str] | None, float]]] = {}

    for snap_path in snaps:
        date_str = snap_path.name
        try:
            profile_raw = load_snapshot_profile(snap_path)
        except Exception as e:
            logger.warning("Could not load snapshot %s: %s", snap_path, e)
            continue

        for (cid, fpath), field in _flatten_profile(profile_raw).items():
            key = (cid, fpath)
            if key not in series:
                series[key] = []
            series[key].append((
                date_str,
                float(field.get("presence_rate") or 0.0),
                str(field.get("type") or ""),
                field.get("enum_values"),
                float(field.get("confidence") or 1.0),
            ))

    field_velocities: list[FieldVelocity] = []
    all_alerts: list[str] = []

    for (cid, fpath), entries in sorted(series.items()):
        dates = [e[0] for e in entries]
        rates = [e[1] for e in entries]
        types = [e[2] for e in entries]
        enum_series = [(e[0], e[3]) for e in entries]
        confs = [e[4] for e in entries]

        trend, slope = _compute_trend(dates, rates)
        enum_growth_rate = _compute_enum_growth_rate(enum_series)
        current_rate = rates[-1] if rates else 0.0
        baseline_rate = rates[0] if rates else 0.0

        # Track type changes
        type_changes: list[str] = []
        for i in range(1, len(types)):
            if types[i] != types[i - 1]:
                type_changes.append(f"{dates[i]}: {types[i-1]} → {types[i]}")

        # Enum history: only record snapshots where enum_values changed
        enum_history: list[dict] = []
        prev_vals: frozenset | None = None
        for d, vals in enum_series:
            curr_vals = frozenset(vals) if vals is not None else None
            if curr_vals != prev_vals and curr_vals is not None:
                enum_history.append({"date": d, "values": sorted(vals or [])})
                prev_vals = curr_vals

        alert = _generate_alert(fpath, trend, current_rate, slope, enum_growth_rate)
        if alert:
            all_alerts.append(alert)

        # Weeks of data
        try:
            d0 = datetime.strptime(dates[0], "%Y-%m-%d")
            d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
            weeks = max((d1 - d0).days // 7, 0)
        except (ValueError, IndexError):
            weeks = 0

        field_velocities.append(FieldVelocity(
            field_path=fpath,
            cluster_id=cid if cid != "__flat__" else None,
            trend=trend,
            trend_slope=slope,
            current_presence_rate=round(current_rate, 4),
            baseline_presence_rate=round(baseline_rate, 4),
            presence_rates=[round(r, 4) for r in rates],
            snapshot_dates=dates,
            confidence_history=[round(c, 4) for c in confs],
            type_changes=type_changes,
            enum_history=enum_history,
            enum_growth_rate=enum_growth_rate,
            alert=alert,
            weeks_of_data=weeks,
        ))

    # Schema stability score: fraction of fields with no alert and trend STABLE or INSUFFICIENT_DATA
    if field_velocities:
        stable_n = sum(
            1 for fv in field_velocities
            if fv.alert is None and fv.trend in (TrendStatus.STABLE, TrendStatus.INSUFFICIENT_DATA)
        )
        stability = round(stable_n / len(field_velocities), 3)
    else:
        stability = 1.0

    return VelocityReport(
        stream_name=stream_name,
        computed_at=now,
        snapshot_count=len(snaps),
        snapshot_dates=snap_dates,
        fields=field_velocities,
        alerts=all_alerts,
        schema_stability_score=stability,
    )


def write_velocity_report(report: VelocityReport, output_dir: str) -> str:
    """
    Write velocity.yaml to schemas/<stream>/velocity.yaml.
    Returns the path written.
    """
    out_path = Path(output_dir) / report.stream_name / "velocity.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a clean dict for YAML output (Pydantic -> dict, then prune None/empty)
    doc: dict = {
        "stream": report.stream_name,
        "computed_at": report.computed_at,
        "snapshot_count": report.snapshot_count,
        "snapshot_dates": report.snapshot_dates,
        "schema_stability_score": report.schema_stability_score,
    }
    if report.alerts:
        doc["alerts"] = report.alerts

    fields_out = []
    for fv in report.fields:
        fd: dict = {
            "field_path": fv.field_path,
            "trend": fv.trend.value,
            "current_presence_rate": fv.current_presence_rate,
            "baseline_presence_rate": fv.baseline_presence_rate,
            "presence_rates": fv.presence_rates,
            "snapshot_dates": fv.snapshot_dates,
            "weeks_of_data": fv.weeks_of_data,
        }
        if fv.cluster_id:
            fd["cluster_id"] = fv.cluster_id
        if fv.trend_slope is not None:
            fd["trend_slope"] = fv.trend_slope
        if fv.type_changes:
            fd["type_changes"] = fv.type_changes
        if fv.enum_history:
            fd["enum_history"] = fv.enum_history
        if fv.enum_growth_rate is not None:
            fd["enum_growth_rate"] = fv.enum_growth_rate
        if fv.alert:
            fd["alert"] = fv.alert
        fields_out.append(fd)

    doc["fields"] = fields_out

    header = (
        f"# StreamForge Velocity Report — {report.stream_name}\n"
        f"# Computed: {report.computed_at}\n"
        f"# Snapshots: {report.snapshot_count}\n"
        f"# Stability score: {report.schema_stability_score:.2f}\n\n"
    )

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.dump(doc, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("Velocity report written: %s", out_path)
    return str(out_path)
