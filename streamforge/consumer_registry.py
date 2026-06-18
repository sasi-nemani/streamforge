"""
streamforge/consumer_registry.py — Consumer Registry & Blast Radius Engine
===========================================================================

The consumer registry answers the question every oncall engineer asks at 2am:
  "This stream just drifted — WHO will break, and HOW BAD is it?"

Design decisions:
  ADR-012: Registry files are YAML, stored alongside schema.yaml in the
           schemas/<stream_name>/ directory. This keeps schema + consumers
           co-located, reviewable in the same PR, and requires zero new
           infrastructure. Git history gives you a full audit trail.

  ADR-013: Consumers declare which FIELDS they use, not just that they
           consume the stream. This is the key insight that enables precise
           blast radius: if `amount` drifts and consumer A only uses
           `user_id`, consumer A is NOT affected.

  ADR-014: Impact scoring = criticality × drift_tier. A Tier-1 drift (optional
           new field) hitting a Tier-1 service (payments pipeline) scores
           higher than Tier-3 drift (field removed) hitting a Tier-3 service
           (analytics dashboard). This surfaces the oncall-relevant alerts.

  ADR-015: The consumer registry is VOLUNTARY. Streams without a consumers.yaml
           still work — drift detection just can't compute blast radius. This
           removes the adoption barrier: teams don't need to register consumers
           before getting schema governance.

File format (schemas/<stream>/consumers.yaml):
──────────────────────────────────────────────
stream: payments.stream_v1
consumers:
  - name: fraud-detection-service
    team: fraud-eng
    contact: slack:#fraud-oncall
    criticality: tier1        # tier1 (most critical) | tier2 | tier3
    schema_version: "1.0.0"
    fields_used:
      - path: amount
        required: true
      - path: user_id
        required: true
      - path: merchant_id     # optional — will log warning if missing but won't break
    description: "Real-time fraud scoring pipeline"
    repo: "github.com/myorg/fraud-detection"
    runbook: "https://wiki.myorg.com/fraud-oncall"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import DriftReport, DriftTier, FieldDrift

# Re-export for patching in tests
try:
    from kafka.admin import KafkaAdminClient  # type: ignore[import]
except ImportError:
    KafkaAdminClient = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ConsumedField:
    """One field that a consumer reads from a stream."""
    path: str                       # dot-notation, e.g., "user.email"
    required: bool = True           # If True, this field being removed/changed breaks the consumer
    transform: str | None = None # e.g., "int(source.amount)" — documents type coercion


@dataclass
class StreamConsumer:
    """
    A service, pipeline, or dashboard that consumes a stream.

    The `contact` field is how to reach the owning team in an incident.
    Prefer Slack channel over individual email — teams rotate oncall.
    """
    name: str
    team: str
    contact: str                        # e.g., "slack:#fraud-oncall" or "pagerduty:fraud-pd"
    criticality: str                    # "tier1" | "tier2" | "tier3"
    schema_version: str                 # which version of schema.yaml they're pinned to
    fields_used: list[ConsumedField] = field(default_factory=list)
    description: str | None = None
    repo: str | None = None          # e.g., "github.com/myorg/fraud-service"
    runbook: str | None = None       # link to oncall runbook

    @property
    def criticality_score(self) -> int:
        """Numeric criticality: tier1=3, tier2=2, tier3=1. Higher = more urgent."""
        return {"tier1": 3, "tier2": 2, "tier3": 1}.get(self.criticality, 1)

    @property
    def required_field_paths(self) -> set[str]:
        """Set of field paths this consumer REQUIRES (breaks if missing/changed)."""
        return {f.path for f in self.fields_used if f.required}

    @property
    def all_field_paths(self) -> set[str]:
        """All field paths this consumer reads (required + optional)."""
        return {f.path for f in self.fields_used}


@dataclass
class ImpactedConsumer:
    """
    Blast radius assessment for one consumer in the context of a specific drift event.
    """
    consumer: StreamConsumer
    impacted_fields: list[str]          # fields in both consumer's fields_used AND drifted fields
    required_field_breaks: list[str]    # required fields that are affected (hard break)
    drift_tiers: list[DriftTier]        # tiers of drifts affecting this consumer
    max_tier: DriftTier
    recommendation: str                 # actionable text for the oncall engineer
    impact_score: int                   # criticality_score × max_tier.value — higher = page first

    @property
    def is_hard_break(self) -> bool:
        """True if any required field is affected — this consumer WILL break."""
        return len(self.required_field_breaks) > 0


@dataclass
class BlastRadius:
    """
    Full blast radius assessment for a drift event across all known consumers.

    This is the primary output of the consumer registry engine. Surfaced in
    drift reports, Slack notifications, and the dashboard.
    """
    stream_name: str
    drift_detected_at: str
    total_consumers: int                # all consumers registered for this stream
    affected_count: int                 # consumers with at least one impacted field
    hard_break_count: int               # consumers with required-field breaks
    impacted: list[ImpactedConsumer]    # sorted by impact_score descending
    unaffected_consumers: list[str]     # names of consumers with no field overlap
    summary: str                        # human-readable one-liner

    @property
    def highest_criticality(self) -> str:
        """tier1 | tier2 | tier3 of the most critical affected consumer."""
        if not self.impacted:
            return "none"
        return self.impacted[0].consumer.criticality

    def to_slack_text(self) -> str:
        """Format blast radius for a Slack notification block."""
        if not self.impacted:
            return "✅ No registered consumers are affected by this drift."

        lines = [f"*Blast Radius — {self.stream_name}*"]
        lines.append(f"{self.affected_count} of {self.total_consumers} consumers affected:")

        for ic in self.impacted[:5]:  # Cap at 5 to avoid flooding Slack
            icon = "🔴" if ic.is_hard_break else "🟡"
            break_str = " *(BREAKING)*" if ic.is_hard_break else ""
            lines.append(
                f"  {icon} *{ic.consumer.name}* ({ic.consumer.team}){break_str}\n"
                f"      Fields: {', '.join(f'`{f}`' for f in ic.impacted_fields[:3])}"
            )
            if ic.consumer.runbook:
                lines.append(f"      Runbook: {ic.consumer.runbook}")

        if len(self.impacted) > 5:
            lines.append(f"  _... and {len(self.impacted) - 5} more — see full report_")

        return "\n".join(lines)


# ── Registry file I/O ──────────────────────────────────────────────────────────

def load_consumers(schemas_dir: str, stream_name: str) -> list[StreamConsumer]:
    """
    Load consumers.yaml for a stream. Returns empty list if file doesn't exist.

    This is intentionally non-fatal — most streams won't have consumers.yaml
    registered yet, especially during initial adoption.

    Args:
        schemas_dir: Root schemas directory (e.g., "schemas").
        stream_name: Stream identifier (e.g., "payments.stream_v1").

    Returns:
        List of StreamConsumer objects. Empty if no consumers.yaml found.
    """
    registry_path = Path(schemas_dir) / stream_name / "consumers.yaml"

    if not registry_path.exists():
        logger.debug("No consumers.yaml found for %s", stream_name)
        return []

    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse consumers.yaml for %s: %s", stream_name, e)
        return []

    consumers = []
    for entry in raw.get("consumers", []):
        try:
            fields_used = [
                ConsumedField(
                    path=f["path"],
                    required=f.get("required", True),
                    transform=f.get("transform"),
                )
                for f in entry.get("fields_used", [])
            ]
            consumers.append(
                StreamConsumer(
                    name=entry["name"],
                    team=entry.get("team", "unknown"),
                    contact=entry.get("contact", ""),
                    criticality=entry.get("criticality", "tier3"),
                    schema_version=entry.get("schema_version", "1.0.0"),
                    fields_used=fields_used,
                    description=entry.get("description"),
                    repo=entry.get("repo"),
                    runbook=entry.get("runbook"),
                )
            )
        except (KeyError, TypeError) as e:
            logger.warning("Skipping malformed consumer entry in %s: %s", registry_path, e)

    logger.info(
        "Loaded consumer registry",
        extra={"stream": stream_name, "count": len(consumers)},
    )
    return consumers


def field_blast_radius(
    schemas_dir: str, field_path: str, streams: list[str]
) -> list[dict[str, Any]]:
    """Cross-topic blast radius for a single field.

    Across every topic that carries ``field_path``, find the registered consumers
    that actually read it. Returns one entry per (consumer, topic) with whether
    the dependency is required (a hard break) and the consumer's criticality —
    sorted hard-breaks-first, then by criticality. Empty when no consumers are
    registered (the honest "unmapped" state).
    """
    impacted: list[dict[str, Any]] = []
    for stream in streams:
        for c in load_consumers(schemas_dir, stream):
            cf = next((f for f in c.fields_used if f.path == field_path), None)
            if cf is None:
                continue
            impacted.append({
                "consumer": c.name,
                "team": c.team,
                "stream": stream,
                "criticality": c.criticality,
                "required": cf.required,
            })
    _crit = {"tier1": 0, "tier2": 1, "tier3": 2}
    impacted.sort(key=lambda x: (not x["required"], _crit.get(x["criticality"], 9)))
    return impacted


def write_consumers_template(schemas_dir: str, stream_name: str) -> str:
    """
    Write a consumers.yaml template for a stream that doesn't have one yet.
    Called by 'streamforge init' to bootstrap consumer registration.

    Returns the path written.
    """
    out = Path(schemas_dir) / stream_name
    out.mkdir(parents=True, exist_ok=True)
    registry_path = out / "consumers.yaml"

    if registry_path.exists():
        logger.debug("consumers.yaml already exists — not overwriting")
        return str(registry_path)

    template = f"""\
# StreamForge Consumer Registry — {stream_name}
# ─────────────────────────────────────────────────────────────────────────────
# Declare every service, pipeline, or dashboard that reads from this stream.
#
# WHY THIS MATTERS:
#   When StreamForge detects schema drift, it uses this file to compute the
#   "blast radius" — which consumers will break and how urgently.
#   A drift in `amount` only pages you if a Tier-1 consumer uses that field.
#
# HOW TO FILL THIS IN:
#   1. List every service in your codebase that calls Kafka.consume("{stream_name}")
#   2. For each service, list the fields it reads (you can start with top-level keys)
#   3. Mark fields as required: true if the service breaks without them
#   4. Set criticality: tier1 for real-time revenue-impacting services
#
# CRITICALITY LEVELS:
#   tier1 — Real-time, revenue-impacting (fraud detection, payment processing)
#   tier2 — Important but recoverable (feature pipelines, ML training)
#   tier3 — Background analytics, dashboards, batch jobs
# ─────────────────────────────────────────────────────────────────────────────

stream: {stream_name}
consumers:
  - name: example-consumer-service
    team: your-team-name
    contact: slack:#your-oncall-channel   # or pagerduty:routing-key
    criticality: tier2
    schema_version: "1.0.0"
    description: "Brief description of what this service does with the stream"
    repo: "github.com/your-org/your-service"
    runbook: "https://wiki.your-org.com/your-service-oncall"
    fields_used:
      # List every field this service reads. Fields not listed are assumed not used.
      # - path: field_name
      #   required: true    # false if the consumer handles missing values gracefully
      - path: id
        required: true
      - path: timestamp
        required: true
      # Add more fields...
"""

    registry_path.write_text(template, encoding="utf-8")
    logger.info("Written consumers template: %s", registry_path)
    return str(registry_path)


# ── Blast Radius Calculation ───────────────────────────────────────────────────

def calculate_blast_radius(
    stream_name: str,
    drift_report: DriftReport,
    schemas_dir: str = "schemas",
) -> BlastRadius:
    """
    Compute which registered consumers are affected by a drift event.

    Algorithm:
      1. Load consumers.yaml for the stream.
      2. For each drift event, identify its field_path.
      3. For each consumer, check if the drifted field overlaps with fields_used.
      4. Score impact = consumer.criticality_score × drift.tier.value.
      5. Return ImpactedConsumer objects sorted by impact_score descending.

    Args:
        stream_name:   Stream identifier.
        drift_report:  DriftReport from drift_detector.py.
        schemas_dir:   Root schemas directory.

    Returns:
        BlastRadius with full impact assessment.
    """
    consumers = load_consumers(schemas_dir, stream_name)

    # Index drifted fields by path for O(1) lookup
    drifted_paths: dict[str, FieldDrift] = {d.field_path: d for d in drift_report.drifts}
    all_drifted_paths = set(drifted_paths.keys())

    impacted: list[ImpactedConsumer] = []
    unaffected: list[str] = []

    for consumer in consumers:
        # Which of this consumer's fields were drifted?
        overlap = consumer.all_field_paths & all_drifted_paths
        if not overlap:
            unaffected.append(consumer.name)
            continue

        # Which required fields are affected? These are hard breaks.
        required_breaks = list(consumer.required_field_paths & all_drifted_paths)

        # Collect the drift tier for each impacted field
        drift_tiers = [drifted_paths[p].tier for p in overlap]
        max_tier = max(drift_tiers, key=lambda t: t.value)

        # Impact score: criticality × max drift tier. Higher = page first.
        impact_score = consumer.criticality_score * max_tier.value

        # Generate a recommendation
        rec = _generate_recommendation(consumer, list(overlap), required_breaks, max_tier)

        impacted.append(
            ImpactedConsumer(
                consumer=consumer,
                impacted_fields=sorted(overlap),
                required_field_breaks=sorted(required_breaks),
                drift_tiers=drift_tiers,
                max_tier=max_tier,
                recommendation=rec,
                impact_score=impact_score,
            )
        )

    # Sort by impact score descending — most urgent first
    impacted.sort(key=lambda ic: ic.impact_score, reverse=True)

    hard_breaks = sum(1 for ic in impacted if ic.is_hard_break)

    summary = _build_summary(stream_name, len(consumers), len(impacted), hard_breaks)

    logger.info(
        "Blast radius calculated",
        extra={
            "stream": stream_name,
            "total_consumers": len(consumers),
            "affected": len(impacted),
            "hard_breaks": hard_breaks,
        },
    )

    return BlastRadius(
        stream_name=stream_name,
        drift_detected_at=drift_report.detected_at,
        total_consumers=len(consumers),
        affected_count=len(impacted),
        hard_break_count=hard_breaks,
        impacted=impacted,
        unaffected_consumers=unaffected,
        summary=summary,
    )


def _generate_recommendation(
    consumer: StreamConsumer,
    impacted_fields: list[str],
    required_breaks: list[str],
    max_tier: DriftTier,
) -> str:
    """Generate an actionable recommendation for oncall engineers."""
    fields_str = ", ".join(f"`{f}`" for f in impacted_fields[:3])
    if len(impacted_fields) > 3:
        fields_str += f" (+{len(impacted_fields) - 3} more)"

    if required_breaks and max_tier == DriftTier.TIER_3:
        return (
            f"🔴 IMMEDIATE ACTION REQUIRED — {consumer.name} will BREAK. "
            f"Required fields affected: {', '.join(required_breaks)}. "
            f"Contact {consumer.contact} now."
            + (f" Runbook: {consumer.runbook}" if consumer.runbook else "")
        )
    elif required_breaks:
        return (
            f"🟡 {consumer.name} likely breaking — required fields affected: "
            f"{', '.join(required_breaks)}. Notify {consumer.contact}."
        )
    else:
        return (
            f"ℹ️  {consumer.name} reads affected fields ({fields_str}) "
            f"but they are marked optional — monitor for errors. "
            f"Contact {consumer.contact} if issues arise."
        )


def _build_summary(
    stream_name: str,
    total: int,
    affected: int,
    hard_breaks: int,
) -> str:
    """Build a one-line human-readable summary for reports and notifications."""
    if total == 0:
        return f"No consumers registered for {stream_name}. Add consumers.yaml to enable blast radius analysis."

    if affected == 0:
        return f"All {total} registered consumer(s) unaffected — no field overlap with drifted fields."

    parts = [f"{affected} of {total} consumer(s) affected"]
    if hard_breaks:
        parts.append(f"{hard_breaks} BREAKING (required field change)")
    return f"{stream_name}: " + ", ".join(parts) + "."


# ── CLI helper: show blast radius in terminal ──────────────────────────────────

def format_blast_radius_table(br: BlastRadius) -> str:
    """Format BlastRadius as a Markdown table for reports and CLI output."""
    if not br.impacted:
        return f"> No registered consumers affected. {br.summary}\n"

    lines = [
        f"## Blast Radius — {br.stream_name}",
        "",
        f"**{br.affected_count}** of {br.total_consumers} consumers affected  ",
        f"**{br.hard_break_count}** hard breaks (required field impacted)  ",
        "",
        "| Consumer | Team | Criticality | Impacted Fields | Hard Break | Action |",
        "|----------|------|-------------|-----------------|------------|--------|",
    ]

    for ic in br.impacted:
        fields_str = ", ".join(f"`{f}`" for f in ic.impacted_fields[:3])
        if len(ic.impacted_fields) > 3:
            fields_str += f" +{len(ic.impacted_fields) - 3}"
        break_str = "🔴 YES" if ic.is_hard_break else "🟡 No"
        lines.append(
            f"| **{ic.consumer.name}** | {ic.consumer.team} | "
            f"{ic.consumer.criticality} | {fields_str} | {break_str} | "
            f"{ic.consumer.contact} |"
        )

    lines += ["", "### Recommendations", ""]
    for ic in br.impacted:
        lines.append(f"- {ic.recommendation}")

    return "\n".join(lines)


# ── Kafka Auto-Discovery ───────────────────────────────────────────────────────

def discover_consumers_from_kafka(topic: str, brokers: str) -> list[dict[str, Any]]:
    """
    Query Kafka Admin API for consumer groups subscribed to `topic`.
    Returns list of dicts: {group_id, member_count, lag, team}
    Falls back to [] on any error — never raises.
    """
    try:
        admin = KafkaAdminClient(bootstrap_servers=brokers, request_timeout_ms=5000)
        groups = admin.list_consumer_groups()
        result: list[dict[str, Any]] = []
        for group_id, _ in groups:
            try:
                desc_list = admin.describe_consumer_groups([group_id])
                for g in desc_list:
                    # Check active members assigned to the topic
                    members_on_topic = [
                        m for m in g.members
                        if any(
                            tp.topic == topic
                            for tp in (
                                m.member_assignment.assignment
                                if m.member_assignment
                                else []
                            )
                        )
                    ]
                    # Also include Empty/Stable groups that have committed offsets
                    # for this topic (they've consumed before, even if inactive now)
                    state = getattr(g, "state", "")
                    if members_on_topic:
                        result.append({
                            "group_id": group_id,
                            "member_count": len(members_on_topic),
                            "lag": None,
                            "team": None,
                            "state": state,
                        })
                    elif state in ("Empty", "Stable") and not g.members:
                        # Check committed offsets to confirm this group used this topic
                        try:
                            offsets = admin.list_consumer_group_offsets(group_id)
                            topic_partitions = [tp for tp in offsets if tp.topic == topic]
                            if topic_partitions:
                                result.append({
                                    "group_id": group_id,
                                    "member_count": 0,
                                    "lag": None,
                                    "team": None,
                                    "state": "inactive",
                                })
                        except Exception:
                            pass
            except Exception:
                continue
        admin.close()
        return result
    except Exception as exc:
        logger.warning("Consumer auto-discovery failed: %s", exc)
        return []
