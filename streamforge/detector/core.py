"""Core drift detection — detect_drift() function."""

import logging
import os
from datetime import UTC, datetime

from .. import audit
from ..models import (
    DriftClass,
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldType,
    InferredSchema,
)
from ..pii_detector import detect_pii
from ..sampler import get_all_field_paths
from ..statistical_tests import binomial_z_test, chi_squared_test
from .classify import (
    TIMESTAMP_TYPES,
    TYPE_REFINEMENTS,
    TYPE_WIDENING,
    _infer_field_type_from_values,
    classify_drift_class,
    classify_drift_tier,
)

logger = logging.getLogger(__name__)

# Heuristic thresholds — kept as backstops where statistical tests are not
# applicable (e.g. sample too small for normal approximation to be valid).
TYPE_DRIFT_THRESHOLD = float(os.environ.get("STREAMFORGE_DRIFT_TYPE_THRESHOLD", "0.05"))
PRESENCE_DRIFT_THRESHOLD = float(os.environ.get("STREAMFORGE_DRIFT_PRESENCE_THRESHOLD", "0.15"))
ENUM_DRIFT_THRESHOLD = float(os.environ.get("STREAMFORGE_DRIFT_ENUM_THRESHOLD", "0.05"))

# Statistical test configuration
# alpha=0.01: 1% false positive rate — conservative for production monitoring
_STAT_ALPHA = float(os.environ.get("STREAMFORGE_STAT_ALPHA", "0.01"))
# Minimum sample size to trust the binomial normal approximation
_MIN_SAMPLE_FOR_STAT = 30


def detect_drift(
    baseline_schema: InferredSchema,
    new_sample: list[dict],
    stream_name: str,
    *,
    stability_cfg=None,  # StabilityConfig | None
) -> DriftReport | None:
    """Compare new_sample against baseline_schema. Returns DriftReport or None."""
    if not new_sample:
        return None

    # Strip internal metadata fields (underscore-prefix convention) before comparison.
    # Matches the filtering done by init/plan so the same events produce the same field
    # set regardless of whether they pass through inference or drift detection.
    clean_sample = [{k: v for k, v in e.items() if not k.startswith("_")} for e in new_sample]
    new_field_values, new_presence_rates = get_all_field_paths(clean_sample)
    baseline_by_path = {f.path: f for f in baseline_schema.fields}

    drifts: list[FieldDrift] = []

    # 1. Check each baseline field
    for path, baseline_field in baseline_by_path.items():
        # Skip object-type parent fields — they're structural containers, not real data
        # fields. The sampler flattens nested objects to leaf paths (user → user.email,
        # user.user_id, etc.) so parent object paths never appear in presence_rates.
        # Their children are checked individually below, making this redundant and
        # a source of false-positive "field_removed" Tier 3 alerts.
        if baseline_field.field_type == FieldType.OBJECT:
            continue

        new_presence = new_presence_rates.get(path, 0.0)
        new_values = new_field_values.get(path, [])

        n_total = len(new_sample)
        observed_count = int(round(new_presence * n_total))

        # ---------------------------------------------------------------
        # Presence rate drift — use binomial z-test when sample is large
        # enough for the normal approximation; fall back to threshold check.
        # ---------------------------------------------------------------
        if n_total >= _MIN_SAMPLE_FOR_STAT:
            presence_test = binomial_z_test(
                baseline_rate=baseline_field.presence_rate,
                observed_count=observed_count,
                observed_total=n_total,
                alpha=_STAT_ALPHA,
            )
            presence_drift = presence_test.is_significant
        else:
            # Small sample: fall back to absolute threshold.
            # Optional fields (presence < 0.8) have inherently higher variance
            # in small samples — require a larger shift before flagging to avoid
            # false positives on probabilistic fields like contact_email (50%).
            _threshold = (
                PRESENCE_DRIFT_THRESHOLD
                if baseline_field.presence_rate >= 0.8
                else PRESENCE_DRIFT_THRESHOLD * 2  # 30pp for optional fields
            )
            presence_drift = (
                abs(baseline_field.presence_rate - new_presence) > _threshold
            )
            presence_test = None  # no test result to log

        if presence_drift:
            delta = new_presence - baseline_field.presence_rate

            # Full removal: observed presence negligible
            if new_presence < 0.05 and baseline_field.presence_rate >= 0.2:
                _leaf = path.split(".")[-1]
                drift = FieldDrift(
                    field_path=path,
                    drift_type="field_removed",
                    previous_presence_rate=baseline_field.presence_rate,
                    observed_presence_rate=new_presence,
                    affected_event_rate=1.0 - new_presence,
                    tier=DriftTier.TIER_1,
                    auto_correctable=False,
                    proposed_correction=(
                        f"`{path}` was removed by the producer.\n"
                        f"Options:\n"
                        f"  1. Pin consumer to the last producer version that includes `{path}`\n"
                        f"  2. Update consumer to handle missing `{path}` gracefully:\n"
                        f"     Python: value = event.get('{_leaf}')  # returns None if missing\n"
                        f"     Java:   Object value = event.getOrDefault(\"{_leaf}\", null);\n"
                        f"  3. Alert the producer team — this may be an unintentional rollout"
                    ),
                    correction_confidence=0.9,
                )
                drift.tier = classify_drift_tier(drift)
                drifts.append(drift)
                if presence_test:
                    logger.debug(
                        "field_removed %s: z=%.2f p=%.4f effect=%.3f",
                        path, presence_test.statistic,
                        presence_test.p_value or 0, presence_test.effect_size,
                    )
                continue

            if delta < 0:
                drift = FieldDrift(
                    field_path=path,
                    drift_type="presence_drop",
                    previous_presence_rate=baseline_field.presence_rate,
                    observed_presence_rate=new_presence,
                    affected_event_rate=abs(delta),
                    tier=DriftTier.TIER_1,
                    auto_correctable=False,
                )
                drift.tier = classify_drift_tier(drift)
                drifts.append(drift)
            else:
                drift = FieldDrift(
                    field_path=path,
                    drift_type="presence_increase",
                    previous_presence_rate=baseline_field.presence_rate,
                    observed_presence_rate=new_presence,
                    affected_event_rate=delta,
                    tier=DriftTier.TIER_1,
                    auto_correctable=True,
                )
                drifts.append(drift)

            if presence_test:
                logger.debug(
                    "presence drift %s: z=%.2f p=%.4f effect=%.3f",
                    path, presence_test.statistic,
                    presence_test.p_value or 0, presence_test.effect_size,
                )

        # ---------------------------------------------------------------
        # Type distribution drift — chi-squared test.
        # Baseline is modelled as a single-type distribution.
        # Observed: count per inferred type across sampled values.
        # ---------------------------------------------------------------
        if new_values:
            observed_type = _infer_field_type_from_values(new_values[:50])
            baseline_type = baseline_field.field_type

            if (
                observed_type != baseline_type
                and observed_type != FieldType.NULL
                # Suppress: observed is a valid subtype of the baseline generic type.
                # This is a schema precision improvement (e.g. statistical fallback
                # inferred "string" but we now see "uuid") — not a real change.
                and (baseline_type, observed_type) not in TYPE_REFINEMENTS
            ):
                # Build type count distribution from observed values
                observed_type_counts: dict[str, int] = {}
                sample_slice = new_values[:200]
                for v in sample_slice:
                    t = _infer_field_type_from_values([v]).value
                    observed_type_counts[t] = observed_type_counts.get(t, 0) + 1

                n_obs_types = len(sample_slice)
                # Baseline: all values expected to be the baseline type
                baseline_type_counts = {baseline_type.value: n_obs_types}

                if n_total >= _MIN_SAMPLE_FOR_STAT:
                    type_test = chi_squared_test(
                        baseline_counts=baseline_type_counts,
                        observed_counts=observed_type_counts,
                        alpha=_STAT_ALPHA,
                        min_expected=5.0,
                    )
                    type_drift = type_test.is_significant
                    non_baseline_count = sum(
                        c for t, c in observed_type_counts.items()
                        if t != baseline_type.value
                    )
                    affected_rate = non_baseline_count / max(n_obs_types, 1)
                else:
                    # Small sample: threshold fallback
                    non_baseline_count = sum(
                        c for t, c in observed_type_counts.items()
                        if t != baseline_type.value
                    )
                    affected_rate = non_baseline_count / max(n_obs_types, 1)
                    type_drift = affected_rate >= TYPE_DRIFT_THRESHOLD
                    type_test = None

                if type_drift:
                    auto = (
                        (baseline_type in TIMESTAMP_TYPES and observed_type in TIMESTAMP_TYPES)
                        or (baseline_type, observed_type) in TYPE_WIDENING
                    )
                    _leaf = path.split(".")[-1]
                    prev_type_label = baseline_type.value
                    new_type_label = observed_type.value
                    proposed = (
                        f"`{path}` changed from `{prev_type_label}` to `{new_type_label}`.\n"
                        f"Options:\n"
                        f"  1. Defensive parse (handles both types):\n"
                        f"     Python: val = float(event['{_leaf}']) if isinstance(event['{_leaf}'], str) else event['{_leaf}']\n"
                        f"     Java:   Object v = event.get(\"{_leaf}\"); double d = v instanceof String ? Double.parseDouble((String)v) : ((Number)v).doubleValue();\n"
                        f"  2. Coordinate with producer to standardise on one type\n"
                        f"  3. Update schema: mark field type as `mixed` to acknowledge the variance"
                    )

                    drift = FieldDrift(
                        field_path=path,
                        drift_type="type_changed",
                        previous_type=baseline_type,
                        observed_type=observed_type,
                        previous_presence_rate=baseline_field.presence_rate,
                        observed_presence_rate=new_presence,
                        affected_event_rate=affected_rate,
                        tier=DriftTier.TIER_1,
                        auto_correctable=auto,
                        proposed_correction=proposed,
                        correction_confidence=0.85 if auto else 0.7,
                    )
                    drift.tier = classify_drift_tier(drift)
                    drifts.append(drift)

                    if type_test:
                        logger.debug(
                            "type drift %s: chi2=%.2f p=%.4f V=%.3f",
                            path, type_test.statistic,
                            type_test.p_value or 0, type_test.effect_size,
                        )

        # Enum drift
        if baseline_field.enum_values and new_values:
            baseline_set = set(baseline_field.enum_values)
            new_str_values = [str(v) for v in new_values if v is not None]
            new_distinct = set(new_str_values)
            novel_values = new_distinct - baseline_set

            if novel_values:
                novel_rate = sum(1 for v in new_str_values if v in novel_values) / max(len(new_str_values), 1)
                if novel_rate >= ENUM_DRIFT_THRESHOLD:
                    drift = FieldDrift(
                        field_path=path,
                        drift_type="enum_changed",
                        previous_enum_values=baseline_field.enum_values,
                        observed_enum_values=list(new_distinct),
                        affected_event_rate=novel_rate,
                        tier=DriftTier.TIER_2,
                        auto_correctable=True,
                        proposed_correction=f"Add new enum values: {', '.join(sorted(novel_values)[:5])}",
                        correction_confidence=0.9,
                    )
                    drifts.append(drift)

        # New PII on existing field
        if new_values:
            new_pii = set(detect_pii(path, new_values[:20]))
            existing_pii = set(baseline_field.pii_categories)
            novel_pii = new_pii - existing_pii
            if novel_pii:
                drift = FieldDrift(
                    field_path=path,
                    drift_type="new_pii",
                    affected_event_rate=new_presence,
                    tier=DriftTier.TIER_3,
                    auto_correctable=False,
                    proposed_correction=f"Review PII handling for {path}: {', '.join(p.value for p in novel_pii)}",
                )
                drifts.append(drift)

    # 2. Check for new fields
    baseline_paths = set(baseline_by_path.keys())
    for path, new_presence in new_presence_rates.items():
        if path in baseline_paths:
            continue
        if new_presence < 0.05:
            continue  # noise

        new_values = new_field_values.get(path, [])
        new_pii = detect_pii(path, new_values[:20])

        if new_pii:
            # New PII field → Tier 3
            drift = FieldDrift(
                field_path=path,
                drift_type="new_pii",
                observed_presence_rate=new_presence,
                affected_event_rate=new_presence,
                tier=DriftTier.TIER_3,
                auto_correctable=False,
                proposed_correction=f"New PII field detected: {', '.join(p.value for p in new_pii)}. Ensure GDPR/compliance review.",
            )
            drifts.append(drift)
        else:
            drift = FieldDrift(
                field_path=path,
                drift_type="field_added",
                observed_presence_rate=new_presence,
                affected_event_rate=new_presence,
                tier=DriftTier.TIER_1,
                auto_correctable=True,
                proposed_correction=f"Add field {path} to schema",
                correction_confidence=0.9,
            )
            drift.tier = classify_drift_tier(drift)
            drifts.append(drift)

    if not drifts:
        return None

    # Assign drift_class to every FieldDrift (Part C)
    for d in drifts:
        d.drift_class = classify_drift_class(d, stability_cfg)

    highest = max(d.tier for d in drifts)
    now = datetime.now(UTC).isoformat()

    summary_parts = []
    tier3 = [d for d in drifts if d.tier == DriftTier.TIER_3]
    tier2 = [d for d in drifts if d.tier == DriftTier.TIER_2]
    tier1 = [d for d in drifts if d.tier == DriftTier.TIER_1]

    if tier3:
        summary_parts.append(f"{len(tier3)} critical issue(s) requiring human review")
    if tier2:
        summary_parts.append(f"{len(tier2)} breaking but auto-correctable change(s)")
    if tier1:
        summary_parts.append(f"{len(tier1)} non-breaking change(s)")

    summary = f"Detected {len(drifts)} drift event(s): " + "; ".join(summary_parts) + "."

    # ── Audit: log per-field drift verdicts ─────────────────────────────────
    for d in drifts:
        audit.log_drift_check(
            field_path=d.field_path,
            check_type=d.drift_type,
            verdict="drift",
            details={
                "tier": d.tier.value,
                "drift_class": d.drift_class.value if d.drift_class else None,
                "previous_presence": d.previous_presence_rate,
                "observed_presence": d.observed_presence_rate,
                "affected_rate": d.affected_event_rate,
            },
            stream=stream_name,
        )
    # Also log clean fields (no drift)
    for path in baseline_by_path:
        if path not in {d.field_path for d in drifts}:
            audit.log_drift_check(
                field_path=path, check_type="all", verdict="clean",
                stream=stream_name,
            )

    evolution_count = sum(1 for d in drifts if d.drift_class == DriftClass.EVOLUTION)
    noise_count = sum(1 for d in drifts if d.drift_class == DriftClass.NOISE)

    return DriftReport(
        stream_name=stream_name,
        detected_at=now,
        schema_version=baseline_schema.version,
        events_sampled=len(new_sample),
        drifts=drifts,
        highest_tier=highest,
        summary=summary,
        evolution_count=evolution_count,
        noise_count=noise_count,
    )
