"""
streamforge.history.proposals — Adaptive baseline update proposals
===================================================================

Generate proposals for schema baseline updates from velocity trend data.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from ..models import (
    BaselineProposal,
    ProposalAction,
    ProposalReport,
    TrendStatus,
    VelocityReport,
)
from .velocity import REMOVAL_THRESHOLD, compute_velocity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

PROPOSAL_MIN_WEEKS: int = int(os.environ.get("SF_HISTORY_PROPOSAL_MIN_WEEKS", "4"))
PROPOSAL_AUTO_CONFIDENCE: float = float(os.environ.get("SF_HISTORY_AUTO_CONFIDENCE", "0.90"))


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
    Heuristic confidence score 0.0-0.95.

    Base = min(weeks / 8, 1.0) x 0.6        (time evidence)
         + trend_clarity x 0.4              (signal clarity)

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
    from ..schema_writer import load_schema

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
            # e.g. "2026-03-16: integer -> float"
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
