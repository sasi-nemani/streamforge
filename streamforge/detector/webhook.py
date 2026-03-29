"""Webhook delivery and drift report console output."""

import logging
from datetime import datetime
from pathlib import Path

import httpx

from ..models import DriftReport, DriftTier

logger = logging.getLogger(__name__)


def post_webhook(drift_report: DriftReport, webhook_url: str) -> None:
    """POST drift report as JSON to webhook URL. Fire and forget."""
    try:
        with httpx.Client(timeout=10) as client:
            client.post(webhook_url, json=drift_report.model_dump(mode="json"))
        logger.info("Webhook posted to %s", webhook_url)
    except Exception as e:
        logger.warning("Webhook delivery failed: %s", e)


def _print_drift_report(report: DriftReport, drift_output_dir: Path, webhook_url: str | None) -> None:
    """Print one drift report to stdout and optionally post to webhook."""
    from ..report_writer import write_drift_report

    now_str = datetime.now().strftime("%H:%M:%S")
    stream_label = report.stream_name
    tier_label = f"Tier {report.highest_tier.value}"
    emoji = "\U0001f534" if report.highest_tier == DriftTier.TIER_3 else "\u26a0"
    cluster_note = ""
    if report.drifts and report.drifts[0].cluster_id:
        cluster_note = f" [{report.drifts[0].cluster_id}]"

    print(
        f"[{now_str}] {emoji} {stream_label}{cluster_note} — "
        f"DRIFT DETECTED — {len(report.drifts)} field(s), {tier_label}"
    )
    for d in report.drifts:
        cid_note = f" [{d.cluster_id}]" if d.cluster_id else ""
        print(
            f"           \u2192 {d.field_path}{cid_note}: {d.drift_type} "
            f"({d.affected_event_rate:.0%} of events) [Tier {d.tier.value}]"
        )

    report_path = write_drift_report(report, str(drift_output_dir))
    print(f"           \u2192 Report: {report_path}")

    if webhook_url:
        post_webhook(report, webhook_url)
