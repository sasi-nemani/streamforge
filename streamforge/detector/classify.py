"""Drift classification — tier and class assignment for FieldDrift instances."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import (
    DriftClass,
    DriftTier,
    FieldDrift,
    FieldType,
)

logger = logging.getLogger(__name__)

# ── Pre-compiled regex patterns for type inference ────────────────────────────
# Module-level compilation: O(1) per call, not O(4 compiles) per call.
# At 8.6M calls/day this saves 8-86 seconds of pure CPU waste.
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
EMAIL_RE = re.compile(r'^[^@]+@[^@]+\.[^@]+$')

# Timestamp types — semantically equivalent conversions are Tier 2
TIMESTAMP_TYPES = {
    FieldType.TIMESTAMP_EPOCH_MS,
    FieldType.TIMESTAMP_ISO8601,
    FieldType.TIMESTAMP_RFC2822,
}

# Type widening pairs — Tier 2
TYPE_WIDENING = {
    (FieldType.INTEGER, FieldType.FLOAT),
    (FieldType.INTEGER, FieldType.MIXED),
    (FieldType.FLOAT, FieldType.MIXED),
    (FieldType.STRING, FieldType.MIXED),
}

# Type refinements — NOT drift.
# When statistical fallback (60% confidence) infers a generic type (string,
# integer) and the drift detector later observes a more-specific compatible
# sub-type, that is a schema precision improvement, not a schema change.
# Checking these pairs silences false-positive alerts caused by the fallback.
TYPE_REFINEMENTS = {
    # string subtypes
    (FieldType.STRING, FieldType.UUID),
    (FieldType.STRING, FieldType.EMAIL),
    (FieldType.STRING, FieldType.PHONE),
    (FieldType.STRING, FieldType.DATE),
    (FieldType.STRING, FieldType.TIMESTAMP_ISO8601),
    (FieldType.STRING, FieldType.TIMESTAMP_RFC2822),
    # integer subtypes
    (FieldType.INTEGER, FieldType.TIMESTAMP_EPOCH_MS),
}


def _new_cluster_threshold() -> float:
    """Return the minimum unknown-event rate that triggers new_cluster drift.

    Defaults to 0.05 (5%).  Override via STREAMFORGE_NEW_CLUSTER_THRESHOLD env var
    (e.g. 0.12 to suppress low-level IoT subtype noise in large multi-schema topics).
    """
    return float(os.environ.get("STREAMFORGE_NEW_CLUSTER_THRESHOLD", "0.05"))


def _routing_regression_floor() -> float:
    """Return the minimum *relative* rate drop that triggers partial routing regression.

    A cluster's observed rate dropping by less than this fraction of its baseline is
    treated as noise and suppressed.  Defaults to 0.20 (20% relative drop).
    Override via STREAMFORGE_ROUTING_REGRESSION_FLOOR env var
    (e.g. 0.10 to be more sensitive, 0.35 to suppress noisy low-volume clusters).
    """
    return float(os.environ.get("STREAMFORGE_ROUTING_REGRESSION_FLOOR", "0.20"))


def _infer_field_type_from_values(values: list[Any]) -> FieldType:
    """Quick statistical type inference on a list of values.

    Uses module-level pre-compiled regex patterns (UUID_RE, ISO_RE, DATE_RE,
    EMAIL_RE) to avoid recompilation on every call.
    """
    if not values:
        return FieldType.NULL

    types: dict[str, int] = {}
    for v in values:
        if v is None:
            t = "null"
        elif isinstance(v, bool):
            t = "boolean"
        elif isinstance(v, int):
            # Epoch ms check: 13-digit integer
            if 1_000_000_000_000 <= v <= 9_999_999_999_999:
                t = "timestamp_epoch_ms"
            else:
                t = "integer"
        elif isinstance(v, float):
            t = "float"
        elif isinstance(v, list):
            t = "array"
        elif isinstance(v, dict):
            t = "object"
        elif isinstance(v, str):
            sv = v.strip()
            if UUID_RE.match(sv):
                t = "uuid"
            elif EMAIL_RE.match(sv):
                t = "email"
            elif ISO_RE.match(sv):
                t = "timestamp_iso8601"
            elif DATE_RE.match(sv):
                t = "date"
            else:
                t = "string"
        else:
            t = "string"
        types[t] = types.get(t, 0) + 1

    non_null = {k: v for k, v in types.items() if k != "null"}
    if not non_null:
        return FieldType.NULL

    if len(non_null) > 1:
        return FieldType.MIXED

    majority = max(non_null, key=lambda k: non_null[k])
    try:
        return FieldType(majority)
    except ValueError:
        return FieldType.STRING


def classify_drift_tier(drift: FieldDrift) -> DriftTier:
    """Classify drift into Tier 1/2/3."""
    dt = drift.drift_type

    if dt == "field_added":
        rate = drift.observed_presence_rate or 0.0
        return DriftTier.TIER_1 if rate < 0.5 else DriftTier.TIER_2

    if dt == "field_removed":
        prev = drift.previous_presence_rate or 0.0
        obs = drift.observed_presence_rate or 0.0
        if prev >= 0.8 and obs < 0.2:
            return DriftTier.TIER_3
        if (prev - obs) > 0.5:
            return DriftTier.TIER_3
        return DriftTier.TIER_2

    if dt == "presence_drop":
        prev = drift.previous_presence_rate or 0.0
        obs = drift.observed_presence_rate or 0.0
        if prev >= 0.8 and obs < 0.2:
            return DriftTier.TIER_3
        return DriftTier.TIER_2

    if dt == "type_changed":
        prev_t = drift.previous_type
        obs_t = drift.observed_type
        # Timestamp format change → Tier 2
        if prev_t in TIMESTAMP_TYPES and obs_t in TIMESTAMP_TYPES:
            return DriftTier.TIER_2
        # Type widening → Tier 2
        if (prev_t, obs_t) in TYPE_WIDENING:
            return DriftTier.TIER_2
        # Any other incompatible type change (narrowing, unrelated) → Tier 3
        return DriftTier.TIER_3

    if dt == "new_pii":
        return DriftTier.TIER_3

    if dt == "enum_changed":
        # New values added → Tier 2
        return DriftTier.TIER_2

    if dt == "presence_increase":
        return DriftTier.TIER_1

    return DriftTier.TIER_2


def classify_drift_class(
    drift: FieldDrift,
    stability_cfg=None,  # StabilityConfig | None
) -> DriftClass:
    """
    Assign a DriftClass to a FieldDrift.

    Called right after classify_drift_tier() — the tier is already set on drift.
    stability_cfg is a StabilityConfig (or None for conservative defaults).

    Rules (in priority order):
      1. correction_confidence < 0.50 → NOISE (low-confidence signal, suppress)
      2. drift_type-specific rules (see table in CLAUDE.md)
    """
    dt = drift.drift_type

    # Rule 0: low-confidence signal → NOISE regardless of drift type.
    # Uses correction_confidence as the proxy for signal quality.
    if drift.correction_confidence is not None and drift.correction_confidence < 0.50:
        return DriftClass.NOISE

    # Rule 1: new cluster (unknown event family)
    if dt == "new_cluster":
        if stability_cfg is not None and stability_cfg.new_cluster_is_evolution:
            return DriftClass.EVOLUTION
        return DriftClass.DRIFT

    # Rule 2: field_added — low presence → EVOLUTION, high presence → DRIFT
    if dt == "field_added":
        observed = drift.observed_presence_rate or 0.0
        return DriftClass.EVOLUTION if observed < 0.5 else DriftClass.DRIFT

    # Rule 3: field_removed → always DRIFT (data always disappears)
    if dt == "field_removed":
        return DriftClass.DRIFT

    # Rule 4: type_changed — widening or timestamp format → EVOLUTION, narrowing → DRIFT
    if dt == "type_changed":
        prev_t = drift.previous_type
        obs_t = drift.observed_type
        # Timestamp format change is semantically equivalent → EVOLUTION
        if prev_t in TIMESTAMP_TYPES and obs_t in TIMESTAMP_TYPES:
            return DriftClass.EVOLUTION
        # Type widening → EVOLUTION
        if (prev_t, obs_t) in TYPE_WIDENING:
            return DriftClass.EVOLUTION
        # Everything else (narrowing, incompatible change) → DRIFT
        return DriftClass.DRIFT

    # Rule 5: enum_changed — only additions → EVOLUTION, any removal → DRIFT
    if dt == "enum_changed":
        prev_vals = set(drift.previous_enum_values or [])
        obs_vals = set(drift.observed_enum_values or [])
        removed = prev_vals - obs_vals
        if removed:
            return DriftClass.DRIFT
        return DriftClass.EVOLUTION

    # Rule 6: presence rate changes
    if dt == "presence_increase":
        return DriftClass.EVOLUTION
    if dt == "presence_drop":
        return DriftClass.DRIFT

    # Catch-all: conservative default → DRIFT
    return DriftClass.DRIFT


def remediation_hint(drift: FieldDrift) -> str:
    """Generate a concrete remediation hint for a drift event.

    Converts detection into actionable guidance -- the operator doesn't
    have to figure out what to do, they just follow the hint.
    """
    dt = drift.drift_type
    path = drift.field_path

    if dt == "field_removed":
        return (
            f"Field '{path}' has been removed (presence {drift.previous_presence_rate:.0%} -> "
            f"{drift.observed_presence_rate:.0%}). "
            f"Action: check producer for field rename or removal. "
            f"If intentional, run `streamforge accept` to update baseline. "
            f"If unintentional, rollback the producer change."
        )

    if dt == "type_changed":
        prev = drift.previous_type.value if drift.previous_type else "unknown"
        obs = drift.observed_type.value if drift.observed_type else "unknown"
        return (
            f"Field '{path}' changed type from {prev} to {obs}. "
            f"Action: update schema.yaml field type to '{obs}', "
            f"then run `streamforge accept`. "
            f"Verify downstream consumers handle the new type."
        )

    if dt == "new_pii":
        observed_pii = getattr(drift, "observed_pii", None)
        cats = ", ".join(c.value for c in observed_pii) if observed_pii else "unknown"
        return (
            f"New PII detected in field '{path}' (category: {cats}). "
            f"Action: IMMEDIATE -- review data flow for compliance. "
            f"Consider masking/encrypting before the data reaches consumers. "
            f"Run `streamforge accept` only after compliance review."
        )

    if dt == "field_added":
        rate = drift.observed_presence_rate or 0.0
        if rate < 0.5:
            return (
                f"New optional field '{path}' appeared ({rate:.0%} presence). "
                f"No action required -- will be auto-accepted after 3 clean cycles."
            )
        return (
            f"New field '{path}' appeared at {rate:.0%} presence. "
            f"Action: review if this is expected, then run `streamforge accept`."
        )

    if dt == "presence_drop":
        return (
            f"Field '{path}' presence dropped from {drift.previous_presence_rate:.0%} "
            f"to {drift.observed_presence_rate:.0%}. "
            f"Action: check if producer is conditionally omitting this field. "
            f"If intentional, run `streamforge accept`."
        )

    if dt == "enum_changed":
        new_vals = drift.observed_enum_values or []
        return (
            f"Field '{path}' has new enum values: {new_vals[:5]}. "
            f"Action: update schema if values are expected, then `streamforge accept`."
        )

    return f"Drift detected on field '{path}' ({dt}). Run `streamforge status` for details."


def _handle_evolution(
    signals: list[FieldDrift],
    stream_name: str,
    schema_dir,          # Path | None
    topic_cfg=None,      # TopicConfig | None
) -> None:
    """
    Handle EVOLUTION-class drift signals.

    Prints an info-level message listing each evolution signal.
    If topic_cfg.vcs_enabled, attempts to trigger the VCS flow (commit_schema).
    Never raises — all errors are caught and logged.
    """
    if not signals:
        return

    try:
        now_str = datetime.now().strftime("%H:%M:%S")
        print(
            f"[{now_str}] \U0001f504 {stream_name} — EVOLUTION: "
            f"{len(signals)} additive change(s) detected (no alert)"
        )
        for s in signals:
            print(f"           \u00b7 {s.field_path}: {s.drift_type} ({s.affected_event_rate:.0%})")
    except Exception as e:
        logger.debug("_handle_evolution print failed: %s", e)

    # VCS flow — only when enabled
    if topic_cfg is None or not getattr(topic_cfg, "vcs_enabled", False):
        return

    try:
        from ..vcs import get_vcs_backend
        from ..vcs.base import SchemaCommitContext

        vcs_cfg = topic_cfg.vcs_config
        backend = get_vcs_backend(vcs_cfg, repo_root=Path("."))
        if backend is None or not backend.is_available():
            logger.debug("VCS backend unavailable — skipping evolution commit")
            return

        ctx = SchemaCommitContext(
            stream_name=stream_name,
            old_version=None,
            new_version="evolution",
            action="evolution",
            drift_summary=f"EVOLUTION: {len(signals)} additive change(s) in {stream_name}",
            tier=1,
            files=[],
        )
        result = backend.commit_schema(ctx)
        if result:
            logger.info("VCS evolution commit: %s", result)
        else:
            logger.warning("VCS evolution commit failed (non-fatal): %s", result)
    except Exception as e:
        logger.warning("_handle_evolution VCS flow failed (non-fatal): %s", e)
