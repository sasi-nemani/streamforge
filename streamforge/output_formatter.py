"""
Human-readable formatting for StreamForge console output.

Maps internal technical terms to plain English for console display.
All formatting logic lives here — keep __main__.py clean.
"""

# Maps drift_type values to plain English descriptions
from datetime import UTC

DRIFT_TYPE_MESSAGES = {
    "field_removed": "field was removed",
    "field_added": "new field appeared",
    "type_changed": "field type changed",
    "presence_drift": "field became much less common",
    "enum_drift": "new values appeared in enum field",
    "format_changed": "field format changed",
    "new_cluster": "new event type appeared in stream",
    "routing_regression": "event type proportion dropped significantly",
}

DRIFT_TIER_LABELS = {
    1: ("blue", "Non-breaking change"),
    2: ("yellow", "Breaking change (auto-correctable)"),
    3: ("red", "Breaking change — human action required"),
}

DRIFT_CLASS_ICONS = {
    "DRIFT": "🔴",
    "EVOLUTION": "🟡",
    "NOISE": "⚪",
}


def describe_drift(drift_type: str, field_path: str, previous=None, observed=None) -> str:
    """
    Return a plain-English description of a drift event.

    Examples:
      describe_drift("field_removed", "amount")
        → "'amount' field was removed"
      describe_drift("type_changed", "created_at", "timestamp_epoch_ms", "timestamp_iso8601")
        → "'created_at' changed: epoch timestamp → ISO date string"
    """
    base = DRIFT_TYPE_MESSAGES.get(drift_type, drift_type.replace("_", " "))

    if drift_type == "type_changed" and previous and observed:
        prev_human = _humanize_type(previous)
        obs_human = _humanize_type(observed)
        return f"'{field_path}' changed: {prev_human} → {obs_human}"
    elif drift_type == "field_removed":
        return f"'{field_path}' field was removed"
    elif drift_type == "field_added":
        return f"new field '{field_path}' appeared"
    elif drift_type == "presence_drift":
        if previous is not None and observed is not None:
            return f"'{field_path}' presence dropped: {previous:.0%} → {observed:.0%} of events"
        return f"'{field_path}' became much less common"
    else:
        return f"'{field_path}': {base}"


def _humanize_type(field_type: str) -> str:
    """Convert internal FieldType strings to human-readable labels."""
    TYPE_LABELS = {
        "timestamp_epoch_ms": "epoch timestamp",
        "timestamp_iso8601": "ISO date string",
        "timestamp_rfc2822": "RFC date string",
        "string": "text",
        "integer": "whole number",
        "float": "decimal number",
        "boolean": "true/false",
        "uuid": "UUID",
        "email": "email address",
        "phone": "phone number",
        "array": "list",
        "object": "nested object",
        "null": "null",
        "mixed": "mixed types",
        "date": "date",
    }
    return TYPE_LABELS.get(field_type, field_type.replace("_", " "))


def format_watch_tick(stream_name: str, events_sampled: int, is_clean: bool) -> str:
    """Format a watch loop tick line."""
    from datetime import datetime
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    if is_clean:
        return f"[{ts}] ✓ {stream_name} — {events_sampled} events checked — no breaking changes"
    else:
        return f"[{ts}] 🔴 {stream_name} — BREAKING CHANGE CAUGHT"


def format_drift_alert(stream_name: str, drifts: list, tier: int) -> str:
    """Format a drift detection alert for console output."""
    from datetime import datetime
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    tier_label = DRIFT_TIER_LABELS.get(tier, (None, f"Tier {tier}"))[1]
    lines = [f"[{ts}] 🔴 {stream_name} — {tier_label}"]
    for d in drifts[:3]:  # show at most 3 drift items inline
        lines.append(f"           → {d}")
    if len(drifts) > 3:
        lines.append(f"           → ... and {len(drifts) - 3} more (see report)")
    return "\n".join(lines)


def format_discover_panel(broker: str, monitored: list, unmonitored: list) -> str:
    """Return the governance posture summary for the discover command."""
    total = len(monitored) + len(unmonitored)
    monitored_str = ", ".join(monitored) if monitored else "none"
    unmonitored_preview = unmonitored[:5]
    unmonitored_str = ", ".join(unmonitored_preview)
    if len(unmonitored) > 5:
        unmonitored_str += f" [+{len(unmonitored) - 5} more]"

    lines = [
        "",
        f"  {len(unmonitored)} of your {total} Kafka topics have NO schema contract.",
        "  Any producer change could silently break downstream consumers.",
        "",
        f"  ✓ Monitored ({len(monitored)}):    {monitored_str}",
        f"  ○ Unmonitored ({len(unmonitored)}):  {unmonitored_str}",
    ]
    if unmonitored:
        first = unmonitored[0]
        lines += [
            "",
            f"  Fix: streamforge init kafka://{first} --brokers {broker}",
        ]
    return "\n".join(lines)


def format_init_success(stream_name: str, field_count: int, confidence: float) -> str:
    """Format the success message after streamforge init completes."""
    return (
        f"\n✓ Schema contract created for {stream_name} "
        f"({field_count} fields, confidence {confidence:.0%})\n"
        f"\n  What happens next:\n"
        f"  • Run 'streamforge watch kafka://{stream_name}' to start monitoring\n"
        f"  • Add the GitHub Action to block breaking changes in CI\n"
        f"  • Your schema is in schemas/{stream_name}/schema.yaml — commit it to Git\n"
    )
