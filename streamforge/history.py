"""
streamforge/history.py — Schema History, Diff, Velocity, and Proposals
========================================================================

Three capabilities built on top of the weekly re-init cycle:

  1. Snapshot  — archive today's profile.yaml to a dated history directory
  2. Diff      — compare two snapshots, classify each change by significance
  3. Velocity  — compute per-field trends across all snapshots → velocity.yaml
  4. Propose   — generate adaptive baseline update proposals from trend data

Storage layout (under schemas/<stream>/):
  profile.yaml                  ← live (current)
  velocity.yaml                 ← computed aggregate, overwritten on each run
  history/
    proposals.md                ← latest proposal report
    YYYY-MM-DD/
      profile.yaml              ← immutable snapshot
      meta.yaml                 ← SnapshotMeta
      diff_<right_date>.md      ← written when comparing this snapshot as the left

Design invariants:
  - No LLM calls. Everything here is deterministic and testable without mocking.
  - Snapshots are immutable once written (overwrite only with explicit --force).
  - velocity.yaml is always derived from snapshots; never the source of truth.
  - Field identity key: (cluster_id, field_path). cluster_id="__flat__" for
    non-multi-schema streams.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .models import (
    BaselineProposal,
    FieldDiffEntry,
    FieldVelocity,
    ProfileDiff,
    ProposalAction,
    ProposalReport,
    SnapshotMeta,
    TrendStatus,
    VelocityReport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable constants — override via environment variables in production
# ---------------------------------------------------------------------------

MIN_SNAPSHOTS_FOR_TREND: int = int(os.environ.get("SF_HISTORY_MIN_SNAPSHOTS", "3"))
REMOVAL_THRESHOLD: float = float(os.environ.get("SF_HISTORY_REMOVAL_THRESHOLD", "0.20"))
ENUM_GROWTH_ALERT_RATE: float = float(os.environ.get("SF_HISTORY_ENUM_ALERT_RATE", "1.0"))
PROPOSAL_MIN_WEEKS: int = int(os.environ.get("SF_HISTORY_PROPOSAL_MIN_WEEKS", "4"))
PROPOSAL_AUTO_CONFIDENCE: float = float(os.environ.get("SF_HISTORY_AUTO_CONFIDENCE", "0.90"))
DECLINING_SLOPE_THRESHOLD: float = -0.002   # presence_rate/day (≈6%/month for weekly snapshots)
VOLATILE_STD_THRESHOLD: float = 0.10        # stddev of presence_rates → volatile

# Type pairs considered "widening" (non-breaking)
_WIDENING_PAIRS: set[frozenset[str]] = {
    frozenset({"integer", "float"}),
    frozenset({"integer", "mixed"}),
    frozenset({"float", "mixed"}),
    frozenset({"string", "mixed"}),
}
# Timestamp types are interchangeable format changes (Tier 2, non-breaking)
_TIMESTAMP_TYPES: frozenset[str] = frozenset({
    "timestamp_epoch_ms", "timestamp_iso8601", "timestamp_rfc2822",
})


# ---------------------------------------------------------------------------
# Snapshot I/O
# ---------------------------------------------------------------------------

def snapshot_dir(output_dir: str, stream_name: str, date: str) -> Path:
    """Return path to a specific snapshot directory (does not create it)."""
    return Path(output_dir) / stream_name / "history" / date


def write_snapshot(
    profile_raw: dict,
    stream_name: str,
    output_dir: str,
    triggered_by: str = "manual",
    date: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """
    Archive profile_raw (as loaded by schema_writer.load_profile) into
    schemas/<stream>/history/<YYYY-MM-DD>/profile.yaml + meta.yaml.

    If a snapshot for today already exists and force=False, logs a warning and
    overwrites it (idempotent re-runs are fine — same-day snapshots are rare
    and should not crash the caller).

    Returns (profile_path, meta_path) as strings.
    """
    today = date or datetime.now(UTC).strftime("%Y-%m-%d")
    snap_dir = snapshot_dir(output_dir, stream_name, today)

    if snap_dir.exists() and not force:
        logger.warning(
            "Snapshot for %s/%s already exists — overwriting", stream_name, today
        )

    snap_dir.mkdir(parents=True, exist_ok=True)

    # Write profile.yaml verbatim
    profile_path = snap_dir / "profile.yaml"
    with open(profile_path, "w", encoding="utf-8") as fh:
        yaml.dump(profile_raw, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Build and write meta.yaml
    sub_schemas = profile_raw.get("sub_schemas", [])
    field_count = sum(len(s.get("fields", [])) for s in sub_schemas)
    meta = SnapshotMeta(
        stream_name=stream_name,
        snapshot_date=today,
        profiled_at=profile_raw.get("profiled_at", today),
        total_events_sampled=profile_raw.get("total_events_sampled", 0),
        cluster_ids=[s["cluster_id"] for s in sub_schemas],
        field_count=field_count,
        triggered_by=triggered_by,
    )
    meta_path = snap_dir / "meta.yaml"
    with open(meta_path, "w", encoding="utf-8") as fh:
        yaml.dump(meta.model_dump(), fh, default_flow_style=False, sort_keys=False)

    logger.info("Snapshot written: %s", snap_dir)
    return str(profile_path), str(meta_path)


def list_snapshots(output_dir: str, stream_name: str) -> list[Path]:
    """
    Return all valid snapshot directories sorted chronologically (oldest first).

    A valid snapshot has both profile.yaml and meta.yaml. YYYY-MM-DD directory
    names sort lexicographically = chronologically, so no date parsing needed.
    """
    history_root = Path(output_dir) / stream_name / "history"
    if not history_root.exists():
        return []
    dirs = sorted(
        d for d in history_root.iterdir()
        if d.is_dir()
        and (d / "profile.yaml").exists()
        and (d / "meta.yaml").exists()
    )
    return dirs


def load_snapshot_profile(snapshot_path: Path) -> dict:
    """Load profile.yaml from a snapshot directory. Raises FileNotFoundError if missing."""
    p = snapshot_path / "profile.yaml"
    if not p.exists():
        raise FileNotFoundError(f"No profile.yaml in snapshot: {snapshot_path}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_snapshot_meta(snapshot_path: Path) -> SnapshotMeta:
    """Load meta.yaml from a snapshot directory. Returns SnapshotMeta model."""
    p = snapshot_path / "meta.yaml"
    if not p.exists():
        raise FileNotFoundError(f"No meta.yaml in snapshot: {snapshot_path}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return SnapshotMeta(**raw)


# ---------------------------------------------------------------------------
# Profile flattening — internal helpers for diff and velocity
# ---------------------------------------------------------------------------

def _flatten_profile(profile_raw: dict) -> dict[tuple[str, str], dict]:
    """
    Flatten a profile.yaml dict into {(cluster_id, field_path): field_dict}.

    For streams with a single sub_schema (or none), cluster_id is "__flat__".
    Skips synthetic parent-object entries (field type == "object" or "array")
    that are injected by _inject_parent_objects — those exist for documentation
    only and should not be diffed as structural fields.
    """
    result: dict[tuple[str, str], dict] = {}
    sub_schemas = profile_raw.get("sub_schemas", [])

    for sub in sub_schemas:
        cid = sub.get("cluster_id", "__flat__")
        for field in sub.get("fields", []):
            ftype = field.get("type", "")
            # Skip injected parent containers (they carry no data themselves)
            if (ftype in ("object", "array") and not field.get("enum_values")
                    and field.get("confidence", 1.0) == 1.0 and not field.get("pii")):
                # Skip pure structural parent containers (no data of their own)
                continue
            result[(cid, field["path"])] = field

    return result


def _days_between(date_a: str, date_b: str) -> int:
    """Return (date_b - date_a).days. Both strings are YYYY-MM-DD."""
    try:
        d_a = datetime.strptime(date_a, "%Y-%m-%d").date()
        d_b = datetime.strptime(date_b, "%Y-%m-%d").date()
        return (d_b - d_a).days
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def _classify_significance(
    change_type: str,
    before: dict | None,
    after: dict | None,
) -> str:
    """
    Classify a field change as "breaking", "non_breaking", or "informational".

    Rules (priority order):
    - removed + was required=True → breaking
    - removed + was required=False → non_breaking
    - type_changed to non-widening, non-timestamp pair → breaking
    - type_changed but widening or timestamp format swap → non_breaking
    - added → non_breaking
    - presence_changed → informational if |delta| < 0.15, else non_breaking
    - enum_changed with values removed → breaking; values only added → non_breaking
    - required_changed True→False → non_breaking; False→True → non_breaking
    - pii_added / pii_removed → informational
    - new_cluster / cluster_removed → non_breaking
    """
    if change_type == "removed":
        return "breaking" if (before or {}).get("required", True) else "non_breaking"

    if change_type == "added":
        return "non_breaking"

    if change_type == "type_changed":
        prev_t = (before or {}).get("type", "")
        curr_t = (after or {}).get("type", "")
        pair = frozenset({prev_t, curr_t})
        if pair in _WIDENING_PAIRS:
            return "non_breaking"
        if prev_t in _TIMESTAMP_TYPES and curr_t in _TIMESTAMP_TYPES:
            return "non_breaking"
        return "breaking"

    if change_type == "enum_changed":
        # If any previous values disappeared → breaking (consumers relying on them break)
        prev_vals = set((before or {}).get("enum_values") or [])
        curr_vals = set((after or {}).get("enum_values") or [])
        return "breaking" if prev_vals - curr_vals else "non_breaking"

    if change_type == "presence_changed":
        before_rate = (before or {}).get("presence_rate", 1.0)
        after_rate = (after or {}).get("presence_rate", 1.0)
        return "non_breaking" if abs(after_rate - before_rate) >= 0.15 else "informational"

    if change_type in ("pii_added", "pii_removed", "required_changed"):
        return "informational"

    if change_type in ("new_cluster", "cluster_removed"):
        return "non_breaking"

    return "informational"


def diff_profiles(left_path: Path, right_path: Path) -> ProfileDiff:
    """
    Compare two snapshot directories and return a structured ProfileDiff.

    Algorithm:
    1. Load and flatten both profiles into {(cluster_id, field_path): field_dict}.
    2. Walk through all keys present in either side.
    3. Emit FieldDiffEntry for each difference; skip if identical.
    4. Handle cluster-level adds/removes by checking cluster_id sets.
    5. Classify each entry's significance and compute aggregates.
    """
    left_meta = load_snapshot_meta(left_path)
    right_meta = load_snapshot_meta(right_path)
    left_profile = load_snapshot_profile(left_path)
    right_profile = load_snapshot_profile(right_path)

    left_date = left_meta.snapshot_date
    right_date = right_meta.snapshot_date
    days = _days_between(left_date, right_date)

    left_fields = _flatten_profile(left_profile)
    right_fields = _flatten_profile(right_profile)

    all_keys = set(left_fields) | set(right_fields)
    changes: list[FieldDiffEntry] = []
    stable_count = 0

    # Cluster-level diff
    left_clusters = {s["cluster_id"] for s in left_profile.get("sub_schemas", [])}
    right_clusters = {s["cluster_id"] for s in right_profile.get("sub_schemas", [])}
    for cid in right_clusters - left_clusters:
        changes.append(FieldDiffEntry(
            field_path="__cluster__",
            cluster_id=cid,
            change_type="new_cluster",
            significance="non_breaking",
        ))
    for cid in left_clusters - right_clusters:
        changes.append(FieldDiffEntry(
            field_path="__cluster__",
            cluster_id=cid,
            change_type="cluster_removed",
            significance="non_breaking",
        ))

    # Field-level diff
    for (cid, path) in sorted(all_keys):
        left_f = left_fields.get((cid, path))
        right_f = right_fields.get((cid, path))

        if left_f is None:
            sig = _classify_significance("added", None, right_f)
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="added", after=right_f, significance=sig,
            ))
            continue

        if right_f is None:
            sig = _classify_significance("removed", left_f, None)
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="removed", before=left_f, significance=sig,
            ))
            continue

        # Both sides have the field — check for changes
        field_changed = False

        # Type changed
        if left_f.get("type") != right_f.get("type"):
            sig = _classify_significance("type_changed", left_f, right_f)
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="type_changed", before=left_f, after=right_f,
                significance=sig,
            ))
            field_changed = True

        # Presence rate changed (>2pp to filter float noise)
        pr_delta = (right_f.get("presence_rate", 1.0) or 0) - (left_f.get("presence_rate", 1.0) or 0)
        if abs(pr_delta) >= 0.02:
            sig = _classify_significance("presence_changed", left_f, right_f)
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="presence_changed", before=left_f, after=right_f,
                delta_presence_rate=round(pr_delta, 4), significance=sig,
            ))
            field_changed = True

        # Enum values changed
        left_enum = set(left_f.get("enum_values") or [])
        right_enum = set(right_f.get("enum_values") or [])
        if left_enum != right_enum and (left_enum or right_enum):
            added_vals = sorted(right_enum - left_enum)
            removed_vals = sorted(left_enum - right_enum)
            sig = _classify_significance("enum_changed", left_f, right_f)
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="enum_changed", before=left_f, after=right_f,
                enum_added=added_vals or None, enum_removed=removed_vals or None,
                significance=sig,
            ))
            field_changed = True

        # PII changed
        left_pii = set(left_f.get("pii") or [])
        right_pii = set(right_f.get("pii") or [])
        if left_pii != right_pii:
            if right_pii - left_pii:
                changes.append(FieldDiffEntry(
                    field_path=path, cluster_id=cid if cid != "__flat__" else None,
                    change_type="pii_added", before=left_f, after=right_f,
                    significance="informational",
                ))
            if left_pii - right_pii:
                changes.append(FieldDiffEntry(
                    field_path=path, cluster_id=cid if cid != "__flat__" else None,
                    change_type="pii_removed", before=left_f, after=right_f,
                    significance="informational",
                ))
            field_changed = True

        # Required flag changed
        if left_f.get("required") != right_f.get("required"):
            changes.append(FieldDiffEntry(
                field_path=path, cluster_id=cid if cid != "__flat__" else None,
                change_type="required_changed", before=left_f, after=right_f,
                significance="informational",
            ))
            field_changed = True

        if not field_changed:
            stable_count += 1

    breaking = sum(1 for c in changes if c.significance == "breaking")
    non_breaking = sum(1 for c in changes if c.significance == "non_breaking")
    informational = sum(1 for c in changes if c.significance == "informational")

    summary = _build_diff_summary(
        left_meta.stream_name, left_date, right_date, days,
        breaking, non_breaking, informational, stable_count,
    )

    return ProfileDiff(
        stream_name=left_meta.stream_name,
        left_date=left_date,
        right_date=right_date,
        days_between=days,
        changes=changes,
        breaking_count=breaking,
        non_breaking_count=non_breaking,
        informational_count=informational,
        fields_stable_count=stable_count,
        summary=summary,
    )


def _build_diff_summary(
    stream_name: str,
    left_date: str,
    right_date: str,
    days: int,
    breaking: int,
    non_breaking: int,
    informational: int,
    stable: int,
) -> str:
    total = breaking + non_breaking + informational
    if total == 0:
        return (
            f"{stream_name}: no schema changes detected between "
            f"{left_date} and {right_date} ({days} days). {stable} fields stable."
        )
    parts = []
    if breaking:
        parts.append(f"{breaking} breaking")
    if non_breaking:
        parts.append(f"{non_breaking} non-breaking")
    if informational:
        parts.append(f"{informational} informational")
    return (
        f"{stream_name}: {total} change(s) over {days} days "
        f"({', '.join(parts)}). {stable} fields stable."
    )


def write_diff_report(diff: ProfileDiff, left_snap_path: Path) -> str:
    """
    Write a human-readable diff_<right_date>.md into the left snapshot directory.
    Returns the path written.
    """
    report_path = left_snap_path / f"diff_{diff.right_date}.md"

    def _field_line(entry: FieldDiffEntry) -> str:
        cid = f" [{entry.cluster_id}]" if entry.cluster_id else ""
        if entry.change_type == "added":
            pr = (entry.after or {}).get("presence_rate", "?")
            ftype = (entry.after or {}).get("type", "?")
            return f"| `{entry.field_path}`{cid} | added | — | `{ftype}` (presence {pr:.0%}) |"
        if entry.change_type == "removed":
            pr = (entry.before or {}).get("presence_rate", "?")
            ftype = (entry.before or {}).get("type", "?")
            return f"| `{entry.field_path}`{cid} | removed | `{ftype}` (presence {pr:.0%}) | — |"
        if entry.change_type == "type_changed":
            prev = (entry.before or {}).get("type", "?")
            curr = (entry.after or {}).get("type", "?")
            return f"| `{entry.field_path}`{cid} | type changed | `{prev}` | `{curr}` |"
        if entry.change_type == "presence_changed":
            prev = (entry.before or {}).get("presence_rate", 0)
            curr = (entry.after or {}).get("presence_rate", 0)
            arrow = "↑" if (entry.delta_presence_rate or 0) > 0 else "↓"
            delta = abs(entry.delta_presence_rate or 0)
            return f"| `{entry.field_path}`{cid} | presence {arrow}{delta:.0%} | {prev:.0%} | {curr:.0%} |"
        if entry.change_type == "enum_changed":
            added = ", ".join(entry.enum_added or []) or "—"
            removed = ", ".join(entry.enum_removed or []) or "—"
            return f"| `{entry.field_path}`{cid} | enum changed | removed: {removed} | added: {added} |"
        if entry.change_type in ("new_cluster", "cluster_removed"):
            label = "new cluster" if entry.change_type == "new_cluster" else "cluster removed"
            cid_str = entry.cluster_id or "?"
            return f"| `__cluster__:{cid_str}` | {label} | — | — |"
        return f"| `{entry.field_path}`{cid} | {entry.change_type} | — | — |"

    breaking = [c for c in diff.changes if c.significance == "breaking"]
    non_breaking = [c for c in diff.changes if c.significance == "non_breaking"]
    informational = [c for c in diff.changes if c.significance == "informational"]
    header = "| Field | Change | Before | After |\n|-------|--------|--------|-------|"

    sections = [
        f"# Schema Diff — {diff.stream_name}\n",
        f"**Left:** {diff.left_date}  \n**Right:** {diff.right_date}  ",
        f"**Days apart:** {diff.days_between}  \n",
        f"## Summary\n{diff.summary}\n",
        f"## Changes ({len(diff.changes)} total — "
        f"{diff.breaking_count} breaking, "
        f"{diff.non_breaking_count} non-breaking, "
        f"{diff.informational_count} informational)\n",
    ]

    if breaking:
        sections.append("### 🔴 Breaking Changes\n")
        sections.append(header)
        sections.extend(_field_line(e) for e in breaking)
        sections.append("")

    if non_breaking:
        sections.append("### ⚠ Non-Breaking Changes\n")
        sections.append(header)
        sections.extend(_field_line(e) for e in non_breaking)
        sections.append("")

    if informational:
        sections.append("### ℹ Informational\n")
        sections.append(header)
        sections.extend(_field_line(e) for e in informational)
        sections.append("")

    if diff.fields_stable_count:
        sections.append(f"---\n\n*{diff.fields_stable_count} field(s) unchanged.*\n")

    report_path.write_text("\n".join(sections), encoding="utf-8")
    logger.info("Diff report written: %s", report_path)
    return str(report_path)


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

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

    # Build a clean dict for YAML output (Pydantic → dict, then prune None/empty)
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


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

def _weeks_of_evidence(snapshot_dates: list[str]) -> int:
    """Return calendar weeks spanned by the snapshot date list."""
    if len(snapshot_dates) < 2:
        return 0
    try:
        d0 = datetime.strptime(snapshot_dates[0], "%Y-%m-%d")
        d1 = datetime.strptime(snapshot_dates[-1], "%Y-%m-%d")
        return max((d1 - d0).days // 7, 0)
    except ValueError:
        return 0


def _proposal_confidence(
    weeks: int,
    trend: TrendStatus,
    presence_rates: list[float],
) -> float:
    """
    Heuristic confidence score 0.0–0.95.

    Base = min(weeks / 8, 1.0) × 0.6        (time evidence)
         + trend_clarity × 0.4              (signal clarity)

    trend_clarity: STABLE/RISING/DECLINING=1.0, VOLATILE=0.5, INSUFFICIENT=0.0
    Deduct 0.10 if stddev(presence_rates) > 0.15 (noisy field).
    """
    clarity_map = {
        TrendStatus.STABLE: 1.0,
        TrendStatus.RISING: 1.0,
        TrendStatus.DECLINING: 1.0,
        TrendStatus.VOLATILE: 0.5,
        TrendStatus.INSUFFICIENT_DATA: 0.0,
    }
    base = min(weeks / 8, 1.0) * 0.6 + clarity_map.get(trend, 0.0) * 0.4
    if len(presence_rates) >= 2:
        mean = sum(presence_rates) / len(presence_rates)
        std = math.sqrt(sum((r - mean) ** 2 for r in presence_rates) / len(presence_rates))
        if std > 0.15:
            base -= 0.10
    return round(min(base, 0.95), 3)


def propose_baseline_updates(
    output_dir: str,
    stream_name: str,
    velocity: VelocityReport | None = None,
    min_weeks: int = PROPOSAL_MIN_WEEKS,
) -> ProposalReport:
    """
    Generate adaptive baseline update proposals from velocity trend data.

    Loads current schema.yaml to know declared state, then compares against
    trend data to propose: promotions, demotions, removals, PII flags, type widenings.

    Returns ProposalReport (does NOT write to disk).
    """
    from .schema_writer import load_schema

    now = datetime.now(UTC).isoformat()

    if velocity is None:
        velocity = compute_velocity(output_dir, stream_name)

    weeks = _weeks_of_evidence(velocity.snapshot_dates)

    # Load current schema.yaml as the declared baseline
    schema_path = Path(output_dir) / stream_name / "schema.yaml"
    schema_fields: dict[str, dict] = {}
    if schema_path.exists():
        try:
            schema = load_schema(str(schema_path))
            schema_fields = {f.path: {
                "required": f.required,
                "type": f.field_type.value,
                "presence_rate": f.presence_rate,
                "pii": [p.value for p in f.pii_categories],
            } for f in schema.fields}
        except Exception as e:
            logger.warning("Could not load schema.yaml for proposals: %s", e)

    proposals: list[BaselineProposal] = []

    for fv in velocity.fields:
        if fv.trend == TrendStatus.INSUFFICIENT_DATA:
            continue

        fweeks = fv.weeks_of_data
        if fweeks < min_weeks:
            continue

        conf = _proposal_confidence(fweeks, fv.trend, fv.presence_rates)
        schema_f = schema_fields.get(fv.field_path)

        # PROMOTE_TO_REQUIRED: consistently high presence, not yet required in schema
        if (
            fv.trend in (TrendStatus.STABLE, TrendStatus.RISING)
            and fv.current_presence_rate >= 0.85
            and fv.baseline_presence_rate >= 0.80
            and schema_f is not None
            and not schema_f.get("required", True)
        ):
            proposals.append(BaselineProposal(
                field_path=fv.field_path,
                cluster_id=fv.cluster_id,
                action=ProposalAction.PROMOTE_TO_REQUIRED,
                current_schema_value="optional",
                proposed_value="required",
                evidence=(
                    f"Present in {fv.current_presence_rate:.0%} of events "
                    f"({fweeks} weeks, trend={fv.trend.value})"
                ),
                confidence=conf,
                weeks_of_evidence=fweeks,
            ))

        # DEMOTE_TO_OPTIONAL: required in schema but consistently low presence
        if (
            fv.trend in (TrendStatus.DECLINING, TrendStatus.STABLE)
            and fv.current_presence_rate < 0.65
            and schema_f is not None
            and schema_f.get("required", True)
        ):
            proposals.append(BaselineProposal(
                field_path=fv.field_path,
                cluster_id=fv.cluster_id,
                action=ProposalAction.DEMOTE_TO_OPTIONAL,
                current_schema_value="required",
                proposed_value="optional",
                evidence=(
                    f"Presence dropped to {fv.current_presence_rate:.0%} "
                    f"(baseline {fv.baseline_presence_rate:.0%}, {fweeks} weeks)"
                ),
                confidence=conf,
                weeks_of_evidence=fweeks,
            ))

        # REMOVE_FIELD: approaching removal threshold with declining trend
        if (
            fv.trend == TrendStatus.DECLINING
            and fv.current_presence_rate < REMOVAL_THRESHOLD
            and schema_f is not None
        ):
            proposals.append(BaselineProposal(
                field_path=fv.field_path,
                cluster_id=fv.cluster_id,
                action=ProposalAction.REMOVE_FIELD,
                current_schema_value=f"presence {fv.current_presence_rate:.0%}",
                proposed_value="remove from schema",
                evidence=(
                    f"Presence {fv.current_presence_rate:.0%} below removal threshold "
                    f"({REMOVAL_THRESHOLD:.0%}), declining trend over {fweeks} weeks"
                ),
                confidence=min(conf, 0.80),  # cap — removals always warrant human review
                weeks_of_evidence=fweeks,
            ))

        # WIDEN_TYPE: consistent type change observed in history
        if fv.type_changes and schema_f is not None:
            latest_change = fv.type_changes[-1]
            # e.g. "2026-03-16: integer → float"
            proposals.append(BaselineProposal(
                field_path=fv.field_path,
                cluster_id=fv.cluster_id,
                action=ProposalAction.WIDEN_TYPE,
                current_schema_value=schema_f.get("type"),
                proposed_value=latest_change.split("→")[-1].strip() if "→" in latest_change else None,
                evidence=f"Type changes observed: {'; '.join(fv.type_changes)}",
                confidence=min(conf, 0.75),
                weeks_of_evidence=fweeks,
            ))

    # Split into auto-appliable and requires-review
    # Removals and type changes always require review regardless of confidence
    _ALWAYS_REVIEW = {ProposalAction.REMOVE_FIELD, ProposalAction.WIDEN_TYPE, ProposalAction.FLAG_NEW_PII}
    auto = [
        p for p in proposals
        if p.confidence >= PROPOSAL_AUTO_CONFIDENCE and p.action not in _ALWAYS_REVIEW
    ]
    review = [p for p in proposals if p not in auto]

    summary = (
        f"{len(proposals)} proposal(s) for {stream_name} "
        f"({len(auto)} auto-appliable, {len(review)} requires review). "
        f"Based on {velocity.snapshot_count} snapshots over {weeks} weeks."
    ) if proposals else (
        f"No proposals for {stream_name} — schema appears stable across "
        f"{velocity.snapshot_count} snapshots."
    )

    return ProposalReport(
        stream_name=stream_name,
        generated_at=now,
        weeks_of_history=weeks,
        proposals=proposals,
        auto_appliable=auto,
        requires_review=review,
        summary=summary,
    )


def write_proposal_report(report: ProposalReport, output_dir: str) -> str:
    """
    Write proposals.md to schemas/<stream>/history/proposals.md.
    Returns the path written.
    """
    out_dir = Path(output_dir) / report.stream_name / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "proposals.md"

    _ACTION_LABELS = {
        ProposalAction.PROMOTE_TO_REQUIRED: "Promote → required",
        ProposalAction.DEMOTE_TO_OPTIONAL:  "Demote → optional",
        ProposalAction.REMOVE_FIELD:        "Remove field",
        ProposalAction.FLAG_NEW_PII:        "Flag new PII",
        ProposalAction.WIDEN_TYPE:          "Widen type",
    }

    def _table_rows(proposals: list[BaselineProposal]) -> str:
        header = "| Field | Cluster | Action | Current | Proposed | Evidence | Confidence |\n"
        header += "|-------|---------|--------|---------|----------|----------|------------|\n"
        rows = []
        for p in proposals:
            cid = p.cluster_id or "—"
            action = _ACTION_LABELS.get(p.action, p.action.value)
            rows.append(
                f"| `{p.field_path}` | {cid} | {action} "
                f"| {p.current_schema_value or '—'} | {p.proposed_value or '—'} "
                f"| {p.evidence} | {p.confidence:.0%} |"
            )
        return header + "\n".join(rows) if rows else "*None*"

    sections = [
        f"# Baseline Update Proposals — {report.stream_name}\n",
        f"**Generated:** {report.generated_at}  ",
        f"**Weeks of history:** {report.weeks_of_history}  ",
        f"**Proposals:** {len(report.proposals)} total\n",
        f"## Summary\n{report.summary}\n",
    ]

    if report.auto_appliable:
        sections.append(
            "## ✅ Auto-Appliable\n"
            "_Apply with `streamforge history propose --apply`_\n"
        )
        sections.append(_table_rows(report.auto_appliable))
        sections.append("")

    if report.requires_review:
        sections.append("## 👀 Requires Human Review\n")
        sections.append(_table_rows(report.requires_review))
        sections.append("")

    out_path.write_text("\n".join(sections), encoding="utf-8")
    logger.info("Proposal report written: %s", out_path)
    return str(out_path)
