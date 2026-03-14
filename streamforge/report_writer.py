import logging
from datetime import datetime
from pathlib import Path

from .models import DriftReport, DriftTier, FieldDrift

logger = logging.getLogger(__name__)

TIER_LABELS = {
    DriftTier.TIER_1: "Tier 1 — Non-breaking",
    DriftTier.TIER_2: "Tier 2 — Breaking (auto-correctable)",
    DriftTier.TIER_3: "Tier 3 — Critical (human required)",
}


def format_drift_detail(drift: FieldDrift) -> str:
    lines = [f"### `{drift.field_path}`"]
    lines.append(f"- **Drift type**: `{drift.drift_type}`")

    if drift.previous_type and drift.observed_type:
        lines.append(f"- **Type**: `{drift.previous_type.value}` → `{drift.observed_type.value}`")

    if drift.previous_presence_rate is not None and drift.observed_presence_rate is not None:
        lines.append(
            f"- **Presence rate**: {drift.previous_presence_rate:.0%} → {drift.observed_presence_rate:.0%}"
        )

    if drift.previous_enum_values and drift.observed_enum_values:
        prev = ", ".join(f"`{v}`" for v in sorted(drift.previous_enum_values)[:10])
        obs = ", ".join(f"`{v}`" for v in sorted(drift.observed_enum_values)[:10])
        lines.append(f"- **Previous enum values**: {prev}")
        lines.append(f"- **Observed enum values**: {obs}")

    lines.append(f"- **Tier**: {TIER_LABELS.get(drift.tier, str(drift.tier))}")
    lines.append(f"- **Affected events**: {drift.affected_event_rate:.0%}")

    if drift.auto_correctable and drift.proposed_correction:
        lines.append(f"- **Proposed correction**: `{drift.proposed_correction}`")
        if drift.correction_confidence is not None:
            lines.append(f"- **Correction confidence**: {drift.correction_confidence:.0%}")

    return "\n".join(lines)


def _recommendations(report: DriftReport) -> str:
    lines = []
    tier3 = [d for d in report.drifts if d.tier == DriftTier.TIER_3]
    tier2 = [d for d in report.drifts if d.tier == DriftTier.TIER_2]
    tier1 = [d for d in report.drifts if d.tier == DriftTier.TIER_1]

    if tier3:
        lines.append("**Critical (Tier 3) — Immediate action required:**")
        for d in tier3:
            lines.append(f"- [ ] Investigate `{d.field_path}`: {d.drift_type}")
            if d.proposed_correction:
                lines.append(f"  - Suggested: {d.proposed_correction}")

    if tier2:
        lines.append("\n**Breaking (Tier 2) — Update consumers:**")
        for d in tier2:
            lines.append(f"- [ ] Update schema for `{d.field_path}`: {d.drift_type}")
            if d.proposed_correction:
                lines.append(f"  - Suggested: `{d.proposed_correction}`")

    if tier1:
        lines.append("\n**Non-breaking (Tier 1) — Optional updates:**")
        for d in tier1:
            lines.append(f"- [ ] Review `{d.field_path}`: {d.drift_type}")

    return "\n".join(lines) if lines else "No specific recommendations."


def write_drift_report(report: DriftReport, output_dir: str) -> str:
    """Write dated drift report markdown. Returns path."""
    out = Path(output_dir) / report.stream_name
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    report_path = out / f"{timestamp}.md"

    tier_label = TIER_LABELS.get(report.highest_tier, str(report.highest_tier))
    drift_details = "\n\n".join(format_drift_detail(d) for d in report.drifts)
    recommendations = _recommendations(report)

    content = f"""# Drift Report — {report.stream_name}
**Detected:** {report.detected_at}
**Schema Version:** {report.schema_version}
**Events Sampled:** {report.events_sampled}
**Highest Severity:** {tier_label}

---

## Summary
{report.summary}

---

## Drift Events ({len(report.drifts)})

{drift_details}

---

## Affected Consumers
> Run `streamforge consumers {report.stream_name}` to see subscribed consumers.
> Consumers with auto_correct enabled will be notified automatically.

---

## Recommended Actions
{recommendations}
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Written drift report: %s", report_path)
    return str(report_path)
