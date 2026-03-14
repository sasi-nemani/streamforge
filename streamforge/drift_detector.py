import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .models import (
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    InferredSchema,
    PIICategory,
)
from .pii_detector import detect_pii
from .sampler import get_all_field_paths, load_events_from_folder, reservoir_sample
from .statistical_tests import (
    TestResult,
    binomial_z_test,
    chi_squared_test,
    psi,
    summarise_field_tests,
)

logger = logging.getLogger(__name__)

# Heuristic thresholds — kept as backstops where statistical tests are not
# applicable (e.g. sample too small for normal approximation to be valid).
TYPE_DRIFT_THRESHOLD = float(os.environ.get("STREAMFORGE_DRIFT_TYPE_THRESHOLD", "0.05"))
PRESENCE_DRIFT_THRESHOLD = 0.15
ENUM_DRIFT_THRESHOLD = 0.05

# Statistical test configuration
# alpha=0.01: 1% false positive rate — conservative for production monitoring
_STAT_ALPHA = float(os.environ.get("STREAMFORGE_STAT_ALPHA", "0.01"))
# Minimum sample size to trust the binomial normal approximation
_MIN_SAMPLE_FOR_STAT = 30

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


def _infer_field_type_from_values(values: list[Any]) -> FieldType:
    """Quick statistical type inference on a list of values."""
    import re
    UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
    EMAIL_RE = re.compile(r'^[^@]+@[^@]+\.[^@]+$')

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
        # New PII detected → Tier 3
        return DriftTier.TIER_3

    if dt == "new_pii":
        return DriftTier.TIER_3

    if dt == "enum_changed":
        # New values added → Tier 2
        return DriftTier.TIER_2

    if dt == "presence_increase":
        return DriftTier.TIER_1

    return DriftTier.TIER_2


def detect_drift(
    baseline_schema: InferredSchema,
    new_sample: list[dict],
    stream_name: str,
) -> Optional[DriftReport]:
    """Compare new_sample against baseline_schema. Returns DriftReport or None."""
    if not new_sample:
        return None

    new_field_values, new_presence_rates = get_all_field_paths(new_sample)
    baseline_by_path = {f.path: f for f in baseline_schema.fields}

    drifts: list[FieldDrift] = []

    # 1. Check each baseline field
    for path, baseline_field in baseline_by_path.items():
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
            # Small sample: fall back to absolute threshold
            presence_drift = (
                abs(baseline_field.presence_rate - new_presence) > PRESENCE_DRIFT_THRESHOLD
            )
            presence_test = None  # no test result to log

        if presence_drift:
            delta = new_presence - baseline_field.presence_rate

            # Full removal: observed presence negligible
            if new_presence < 0.05 and baseline_field.presence_rate >= 0.2:
                drift = FieldDrift(
                    field_path=path,
                    drift_type="field_removed",
                    previous_presence_rate=baseline_field.presence_rate,
                    observed_presence_rate=new_presence,
                    affected_event_rate=1.0 - new_presence,
                    tier=DriftTier.TIER_1,
                    auto_correctable=False,
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

            if observed_type != baseline_type and observed_type != FieldType.NULL:
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
                    proposed = None
                    if baseline_type in TIMESTAMP_TYPES and observed_type in TIMESTAMP_TYPES:
                        proposed = f"timestamp_parse(source.{path.split('.')[-1]})"

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
                        correction_confidence=0.85 if auto else None,
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

    highest = max(d.tier for d in drifts)
    now = datetime.now(timezone.utc).isoformat()

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

    return DriftReport(
        stream_name=stream_name,
        detected_at=now,
        schema_version=baseline_schema.version,
        events_sampled=len(new_sample),
        drifts=drifts,
        highest_tier=highest,
        summary=summary,
    )


def post_webhook(drift_report: DriftReport, webhook_url: str) -> None:
    """POST drift report as JSON to webhook URL. Fire and forget."""
    try:
        with httpx.Client(timeout=10) as client:
            client.post(webhook_url, json=drift_report.model_dump(mode="json"))
        logger.info("Webhook posted to %s", webhook_url)
    except Exception as e:
        logger.warning("Webhook delivery failed: %s", e)


def watch_stream(
    stream_path: str,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    webhook_url: Optional[str] = None,
) -> None:
    """Main watch loop. Runs until Ctrl+C."""
    from .report_writer import write_drift_report
    from .schema_writer import load_schema

    baseline = load_schema(schema_path)
    stream_name = baseline.stream_name
    drift_output_dir = Path("drift_reports")

    logger.info("Watching %s every %ds (schema: %s)", stream_path, poll_interval_seconds, schema_path)

    last_mtime: dict[str, float] = {}

    try:
        while True:
            now_str = datetime.now().strftime("%H:%M:%S")

            # Load only modified files since last check
            folder = Path(stream_path)
            files = sorted(
                [f for f in folder.rglob("*") if f.suffix in (".ndjson", ".json") and f.is_file()]
            )

            new_events = []
            for file_path in files:
                mtime = file_path.stat().st_mtime
                prev_mtime = last_mtime.get(str(file_path), 0.0)
                if mtime > prev_mtime:
                    last_mtime[str(file_path)] = mtime
                    # Load events from this file
                    import json as _json
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    ev = _json.loads(line)
                                    if isinstance(ev, dict):
                                        new_events.append(ev)
                                except _json.JSONDecodeError:
                                    pass
                    except OSError:
                        pass

            if not new_events:
                # Re-read all if no new files yet (first run)
                if not last_mtime:
                    new_events = load_events_from_folder(stream_path)
                    for file_path in files:
                        last_mtime[str(file_path)] = file_path.stat().st_mtime

            sample = reservoir_sample(new_events, sample_size) if new_events else []

            if not sample:
                print(f"[{now_str}] ○ {stream_name} — no events to sample")
                time.sleep(poll_interval_seconds)
                continue

            report = detect_drift(baseline, sample, stream_name)

            if report is None:
                print(f"[{now_str}] ✓ {stream_name} — {len(sample)} events sampled — schema clean")
            else:
                tier_label = f"Tier {report.highest_tier.value}"
                emoji = "🔴" if report.highest_tier == DriftTier.TIER_3 else "⚠"
                print(f"[{now_str}] {emoji} {stream_name} — DRIFT DETECTED — {len(report.drifts)} field(s), {tier_label}")
                for d in report.drifts:
                    print(f"           → {d.field_path}: {d.drift_type} ({d.affected_event_rate:.0%} of events) [Tier {d.tier.value}]")

                report_path = write_drift_report(report, str(drift_output_dir))
                print(f"           → Report: {report_path}")

                if webhook_url:
                    post_webhook(report, webhook_url)

            time.sleep(poll_interval_seconds)

    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Watch stopped.")
