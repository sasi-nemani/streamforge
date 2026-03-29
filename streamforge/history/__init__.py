"""
streamforge.history — Schema History, Diff, Velocity, and Proposals
====================================================================

Re-exports all public names from sub-modules for backward compatibility.

Storage layout (under schemas/<stream>/):
  profile.yaml                  <- live (current)
  velocity.yaml                 <- computed aggregate, overwritten on each run
  history/
    proposals.md                <- latest proposal report
    YYYY-MM-DD/
      profile.yaml              <- immutable snapshot
      meta.yaml                 <- SnapshotMeta
      diff_<right_date>.md      <- written when comparing this snapshot as the left
"""

# --- snapshot ---
# --- diff ---
from .diff import (
    _TIMESTAMP_TYPES,
    _WIDENING_PAIRS,
    _build_diff_summary,
    _classify_significance,
    _days_between,
    _flatten_profile,
    diff_profiles,
    write_diff_report,
)

# --- proposals ---
from .proposals import (
    PROPOSAL_AUTO_CONFIDENCE,
    PROPOSAL_MIN_WEEKS,
    _proposal_confidence,
    _weeks_of_evidence,
    propose_baseline_updates,
    write_proposal_report,
)
from .snapshot import (
    list_snapshots,
    load_snapshot_meta,
    load_snapshot_profile,
    snapshot_dir,
    write_snapshot,
)

# --- velocity ---
from .velocity import (
    DECLINING_SLOPE_THRESHOLD,
    ENUM_GROWTH_ALERT_RATE,
    MIN_SNAPSHOTS_FOR_TREND,
    REMOVAL_THRESHOLD,
    VOLATILE_STD_THRESHOLD,
    _compute_enum_growth_rate,
    _compute_trend,
    _generate_alert,
    compute_velocity,
    write_velocity_report,
)

__all__ = [
    # snapshot
    "snapshot_dir",
    "write_snapshot",
    "list_snapshots",
    "load_snapshot_profile",
    "load_snapshot_meta",
    # diff
    "_WIDENING_PAIRS",
    "_TIMESTAMP_TYPES",
    "_flatten_profile",
    "_days_between",
    "_classify_significance",
    "diff_profiles",
    "_build_diff_summary",
    "write_diff_report",
    # velocity
    "MIN_SNAPSHOTS_FOR_TREND",
    "REMOVAL_THRESHOLD",
    "ENUM_GROWTH_ALERT_RATE",
    "DECLINING_SLOPE_THRESHOLD",
    "VOLATILE_STD_THRESHOLD",
    "_compute_trend",
    "_compute_enum_growth_rate",
    "_generate_alert",
    "compute_velocity",
    "write_velocity_report",
    # proposals
    "PROPOSAL_MIN_WEEKS",
    "PROPOSAL_AUTO_CONFIDENCE",
    "_weeks_of_evidence",
    "_proposal_confidence",
    "propose_baseline_updates",
    "write_proposal_report",
]
