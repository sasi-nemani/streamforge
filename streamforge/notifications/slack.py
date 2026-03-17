"""
streamforge/notifications/slack.py — Slack Rich Notifications
=============================================================

Sends structured, actionable Slack alerts when schema drift is detected.
Uses Slack Block Kit for rich formatting — not plain text webhooks.

Design decisions:
  ADR-026: Block Kit over plain text. Plain text webhooks produce unreadable
           walls of text at 2am. Block Kit gives us colour-coded severity
           indicators, inline code formatting for field names, action buttons,
           and proper markdown. Every element is purposeful.

  ADR-027: Fire-and-forget delivery with a 10s timeout. We never block the
           drift detection loop waiting for Slack. If the webhook fails
           (Slack outage, rate limit), we log the error and continue. The
           drift report is always written to disk first — Slack is a delivery
           channel, not the source of truth.

  ADR-028: One message per drift event, not one per drifted field. A stream
           with 10 drifted fields should produce ONE Slack message (batched)
           not 10. Oncall engineers don't need 10 pings — they need context.

  ADR-029: We include a direct link to the drift report file. In a real
           deployment this would link to a dashboard URL. In the MVP it's a
           relative path. The infrastructure to make it a real URL is a config
           option (dashboard_base_url).

Block Kit reference: https://api.slack.com/block-kit
Incoming webhooks: https://api.slack.com/messaging/webhooks
"""

from __future__ import annotations

import logging
import time

import httpx

from ..models import DriftReport, DriftTier

logger = logging.getLogger(__name__)

# Timeout for Slack webhook POST. Never block longer than this.
_WEBHOOK_TIMEOUT_S = 10

# Slack emoji/icon per drift tier
_TIER_EMOJI = {
    DriftTier.TIER_1: ":information_source:",
    DriftTier.TIER_2: ":warning:",
    DriftTier.TIER_3: ":red_circle:",
}

# Slack sidebar colour per tier (left border of the attachment)
_TIER_COLOUR = {
    DriftTier.TIER_1: "#FF9F0A",  # Apple orange — informational
    DriftTier.TIER_2: "#FF9F0A",  # Apple orange — breaking
    DriftTier.TIER_3: "#FF3B30",  # Apple red — critical
}

# Human-readable tier labels
_TIER_LABEL = {
    DriftTier.TIER_1: "Tier 1 — Non-breaking",
    DriftTier.TIER_2: "Tier 2 — Breaking (manageable)",
    DriftTier.TIER_3: "Tier 3 — CRITICAL",
}


def build_slack_payload(
    drift_report: DriftReport,
    blast_radius_text: str | None = None,
    mention: str = "<!here>",
    report_path: str | None = None,
    dashboard_url: str | None = None,
) -> dict:
    """
    Build a Slack Block Kit payload for a drift notification.

    Args:
        drift_report:      The DriftReport to notify about.
        blast_radius_text: Pre-formatted blast radius text (from consumer_registry).
        mention:           Slack mention string. "<!here>" pings online members.
                           Use "" to suppress mentions for Tier 1 alerts.
        report_path:       Local path to the drift report .md file.
        dashboard_url:     If set, "Open Dashboard" button links here.

    Returns:
        Slack API payload dict. Pass to post_notification().
    """
    tier = drift_report.highest_tier
    emoji = _TIER_EMOJI[tier]
    colour = _TIER_COLOUR[tier]
    tier_label = _TIER_LABEL[tier]

    # ── Header block ──────────────────────────────────────────────────────────
    header_text = f"{emoji} *Schema Drift Detected — {drift_report.stream_name}*"
    if tier == DriftTier.TIER_3 and mention:
        header_text = f"{mention} {header_text}"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Schema Drift — {drift_report.stream_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": header_text,
            },
        },
        {"type": "divider"},
    ]

    # ── Metadata context row ──────────────────────────────────────────────────
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"*Stream:* `{drift_report.stream_name}`"},
            {"type": "mrkdwn", "text": f"*Detected:* {drift_report.detected_at[:19].replace('T', ' ')} UTC"},
            {"type": "mrkdwn", "text": f"*Severity:* {tier_label}"},
            {"type": "mrkdwn", "text": f"*Events sampled:* {drift_report.events_sampled:,}"},
        ],
    })

    # ── Drift summary ─────────────────────────────────────────────────────────
    drift_count = len(drift_report.drifts)
    t3 = sum(1 for d in drift_report.drifts if d.tier == DriftTier.TIER_3)
    t2 = sum(1 for d in drift_report.drifts if d.tier == DriftTier.TIER_2)
    t1 = sum(1 for d in drift_report.drifts if d.tier == DriftTier.TIER_1)

    summary_parts = [f"*{drift_count} drift event(s) detected*"]
    if t3:
        summary_parts.append(f":red_circle: {t3} critical")
    if t2:
        summary_parts.append(f":warning: {t2} breaking")
    if t1:
        summary_parts.append(f":information_source: {t1} informational")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "  •  ".join(summary_parts),
        },
    })

    # ── Per-drift field details (cap at 8 to avoid oversized messages) ────────
    shown = drift_report.drifts[:8]
    drift_lines = []
    for d in shown:
        t_emoji = _TIER_EMOJI[d.tier]
        field_str = f"`{d.field_path}`"

        if d.drift_type == "type_changed":
            detail = f"type changed: `{d.previous_type.value}` → `{d.observed_type.value}` ({d.affected_event_rate:.0%} of events)"
        elif d.drift_type == "field_removed":
            detail = f"field *removed* — was {(d.previous_presence_rate or 0):.0%} present, now {(d.observed_presence_rate or 0):.0%}"
        elif d.drift_type == "field_added":
            presence = d.observed_presence_rate or 0
            detail = f"new {'required' if presence >= 0.8 else 'optional'} field added ({presence:.0%} presence)"
        elif d.drift_type == "new_pii":
            detail = "new PII field detected — GDPR/CCPA review required"
        elif d.drift_type == "enum_changed":
            detail = f"new enum values in {d.affected_event_rate:.0%} of events"
        elif d.drift_type == "presence_drop":
            detail = f"presence dropped: {(d.previous_presence_rate or 0):.0%} → {(d.observed_presence_rate or 0):.0%}"
        else:
            detail = d.drift_type

        drift_lines.append(f"{t_emoji} {field_str} — {detail}")

    if len(drift_report.drifts) > 8:
        drift_lines.append(f"_... and {len(drift_report.drifts) - 8} more drift events_")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(drift_lines),
        },
    })

    # ── Blast radius (if available) ───────────────────────────────────────────
    if blast_radius_text:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": blast_radius_text[:2_900],  # Slack block text limit is 3000 chars
            },
        })

    # ── LLM-generated summary ─────────────────────────────────────────────────
    if drift_report.summary:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary:*\n{drift_report.summary}",
            },
        })

    # ── Action buttons ────────────────────────────────────────────────────────
    action_elements = []

    if dashboard_url:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Open Dashboard", "emoji": True},
            "url": dashboard_url,
            "style": "primary",
        })

    if report_path:
        # In a SaaS context this would be a real URL. For now, include as text.
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Report saved to: `{report_path}`"},
            ],
        })

    if action_elements:
        blocks.append({
            "type": "actions",
            "elements": action_elements,
        })

    # ── Assemble final payload ────────────────────────────────────────────────
    # We use attachments for the coloured sidebar. The blocks go into the
    # attachment, not the top-level payload, to get the colour bar.
    return {
        "text": f"StreamForge: Schema drift in {drift_report.stream_name} ({tier_label})",
        "attachments": [
            {
                "color": colour,
                "blocks": blocks,
            }
        ],
    }


def post_notification(
    webhook_url: str,
    drift_report: DriftReport,
    blast_radius_text: str | None = None,
    mention: str = "<!here>",
    min_tier: int = 2,
    report_path: str | None = None,
    dashboard_url: str | None = None,
) -> bool:
    """
    Post a drift notification to Slack via an incoming webhook.

    Implements fire-and-forget (see ADR-027): returns True on success,
    False on any failure. Never raises — the drift detection loop must
    not fail because Slack is down.

    Args:
        webhook_url:       Slack incoming webhook URL.
        drift_report:      The DriftReport to notify about.
        blast_radius_text: Pre-formatted blast radius text.
        mention:           Slack mention string.
        min_tier:          Only notify if highest tier >= this value (1/2/3).
        report_path:       Local path to the drift report file.
        dashboard_url:     Dashboard URL for the "Open Dashboard" button.

    Returns:
        True if Slack accepted the message (HTTP 200), False otherwise.
    """
    # Tier filter — don't ping oncall for Tier 1 if configured that way
    if drift_report.highest_tier.value < min_tier:
        logger.debug(
            "Skipping Slack notification (tier %d < min_tier %d)",
            drift_report.highest_tier.value,
            min_tier,
        )
        return False

    payload = build_slack_payload(
        drift_report=drift_report,
        blast_radius_text=blast_radius_text,
        mention=mention if drift_report.highest_tier == DriftTier.TIER_3 else "",
        report_path=report_path,
        dashboard_url=dashboard_url,
    )

    start = time.monotonic()
    try:
        response = httpx.post(
            webhook_url,
            json=payload,
            timeout=_WEBHOOK_TIMEOUT_S,
            headers={"Content-Type": "application/json"},
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        if response.status_code == 200:
            logger.info(
                "Slack notification sent",
                extra={
                    "stream": drift_report.stream_name,
                    "tier": drift_report.highest_tier.value,
                    "elapsed_ms": round(elapsed_ms),
                },
            )
            return True
        else:
            logger.warning(
                "Slack webhook returned non-200",
                extra={
                    "status": response.status_code,
                    "body": response.text[:200],
                    "stream": drift_report.stream_name,
                },
            )
            return False

    except httpx.TimeoutException:
        logger.warning(
            "Slack webhook timed out after %ds",
            _WEBHOOK_TIMEOUT_S,
            extra={"stream": drift_report.stream_name},
        )
        return False

    except Exception as e:
        logger.error(
            "Failed to post Slack notification: %s",
            e,
            extra={"stream": drift_report.stream_name},
            exc_info=True,
        )
        return False


def test_webhook(webhook_url: str, stream_name: str = "test-stream") -> bool:
    """
    Send a test message to verify the webhook URL is valid.
    Called by 'streamforge notify test --webhook <url>'.
    """
    payload = {
        "text": f"✅ StreamForge webhook test successful for stream: `{stream_name}`",
        "attachments": [
            {
                "color": "#34C759",  # Apple green
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                "*StreamForge is connected!* :white_check_mark:\n"
                                f"This channel will receive drift alerts for `{stream_name}`.\n"
                                "Configure alert sensitivity in `config.yaml` → "
                                "`notifications.slack.min_tier`."
                            ),
                        },
                    }
                ],
            }
        ],
    }
    try:
        r = httpx.post(webhook_url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error("Webhook test failed: %s", e)
        return False
