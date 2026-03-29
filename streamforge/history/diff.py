"""
streamforge.history.diff — Profile Diff Engine
================================================

Compare two snapshot directories and classify each change by significance.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..models import FieldDiffEntry, ProfileDiff
from .snapshot import load_snapshot_meta, load_snapshot_profile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants shared with other modules via __init__.py
# ---------------------------------------------------------------------------

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
# Diff classification
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


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

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
