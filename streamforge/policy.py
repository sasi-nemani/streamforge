"""
stream_policy.yaml — per-stream configuration for drift response.

The policy file lives alongside the schema:
  schemas/<stream_name>/stream_policy.yaml

It is written by `streamforge init` with safe defaults and can be edited
by hand without breaking the tool. All fields have sensible defaults so
the file can be partially specified.

Policy fields:
  stream:               Stream name (informational, matches the folder name)
  sample_size:          How many events to sample per watch cycle
  poll_interval_seconds: Watch loop cadence
  alert_tier:           Minimum tier that triggers an alert (1=all, 2=breaking+, 3=critical)
  actions:              What to do at each tier — log | alert | block
  webhook_url:          Optional HTTP endpoint for drift notifications

Action meanings:
  log    — write drift report to disk, dim console line
  alert  — write drift report, highlighted console output
  block  — write drift report, highlighted console, exit 1 (CI gate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class StreamPolicy:
    stream: str
    sample_size: int = 200
    poll_interval_seconds: int = 30
    alert_tier: int = 2          # 1=all, 2=breaking+, 3=critical only
    actions: dict[str, str] = field(default_factory=lambda: {
        "tier_1": "log",
        "tier_2": "alert",
        "tier_3": "block",
    })
    webhook_url: Optional[str] = None

    def action_for(self, tier: int) -> str:
        """Return the configured action for a drift tier."""
        return self.actions.get(f"tier_{tier}", "alert")

    def should_alert(self, tier: int) -> bool:
        return tier >= self.alert_tier

    def should_block(self, tier: int) -> bool:
        return self.action_for(tier) == "block"


_POLICY_TEMPLATE = """\
# StreamForge Stream Policy — {stream}
# Edit this file to control how drift is handled for this stream.
# Changes take effect on the next 'streamforge watch' or 'streamforge plan' run.

stream: {stream}

# How many events to sample per watch cycle
sample_size: {sample_size}

# Watch loop cadence (seconds)
poll_interval_seconds: {poll_interval_seconds}

# Minimum drift tier that triggers an alert (1=all, 2=breaking+, 3=critical only)
alert_tier: {alert_tier}

# Action per tier: log | alert | block
#   log   — write to drift_reports/, dim console line
#   alert — write to drift_reports/, highlighted console output
#   block — write to drift_reports/, highlighted console, exit 1 (CI gate)
actions:
  tier_1: {tier_1}
  tier_2: {tier_2}
  tier_3: {tier_3}

# Optional webhook URL for drift notifications (null to disable)
webhook_url: {webhook_url}
"""


def write_policy(policy: StreamPolicy, output_dir: str) -> str:
    """Write stream_policy.yaml. Returns the path written."""
    path = Path(output_dir) / policy.stream / "stream_policy.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _POLICY_TEMPLATE.format(
        stream=policy.stream,
        sample_size=policy.sample_size,
        poll_interval_seconds=policy.poll_interval_seconds,
        alert_tier=policy.alert_tier,
        tier_1=policy.actions.get("tier_1", "log"),
        tier_2=policy.actions.get("tier_2", "alert"),
        tier_3=policy.actions.get("tier_3", "block"),
        webhook_url=policy.webhook_url or "null",
    )
    path.write_text(content, encoding="utf-8")
    return str(path)


def load_policy(schema_dir: str, stream_name: str) -> StreamPolicy:
    """
    Load stream_policy.yaml from the schema directory.
    Returns default policy if the file does not exist.
    """
    path = Path(schema_dir) / stream_name / "stream_policy.yaml"
    if not path.exists():
        return StreamPolicy(stream=stream_name)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    actions = raw.get("actions", {})
    return StreamPolicy(
        stream=raw.get("stream", stream_name),
        sample_size=int(raw.get("sample_size", 200)),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 30)),
        alert_tier=int(raw.get("alert_tier", 2)),
        actions={
            "tier_1": actions.get("tier_1", "log"),
            "tier_2": actions.get("tier_2", "alert"),
            "tier_3": actions.get("tier_3", "block"),
        },
        webhook_url=raw.get("webhook_url") or None,
    )
