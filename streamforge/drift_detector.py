import json as _json
import logging
import os
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .models import (
    DriftClass,
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    InferredSchema,
)
from .pii_detector import detect_pii
from .sampler import get_all_field_paths, load_events_from_folder, reservoir_sample
from .statistical_tests import (
    binomial_z_test,
    chi_squared_test,
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

# Minimum cluster events in the watch window before drift checks run.
# Clusters with fewer events are skipped with a debug log — they are under-sampled
# in this poll cycle, not necessarily a real routing regression (which requires
# baseline_rate>=10% AND zero events in a >=30-event sample — see below).
MIN_CLUSTER_EVENTS_FOR_DRIFT = int(
    os.environ.get("STREAMFORGE_MIN_CLUSTER_EVENTS_FOR_DRIFT", "200")
)


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


def _infer_field_type_from_values(values: list[Any]) -> FieldType:
    """Quick statistical type inference on a list of values."""
    import re
    UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
    DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')   # YYYY-MM-DD (date without time)
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
        from .vcs import VCSConfig, get_vcs_backend
        from .vcs.base import SchemaCommitContext

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


# ---------------------------------------------------------------------------
# P1-B — Rolling event window
# ---------------------------------------------------------------------------

class EventWindow:
    """
    Bounded rolling buffer of recent stream events used as the drift comparison
    population.  Each watch poll adds newly-seen events; the oldest fall off
    when capacity is reached (collections.deque maxlen behaviour).

    Sampling from the full window — rather than from only the latest batch —
    gives statistically stable signals and makes slow drift (e.g. a field
    presence rate falling from 80% to 60% over hours) detectable.
    """

    def __init__(self, capacity: int = 2000) -> None:
        self._buf: deque[dict] = deque(maxlen=capacity)

    def add(self, events: list[dict]) -> None:
        """Append new events; oldest are evicted automatically when at capacity."""
        self._buf.extend(events)

    def sample(self, n: int) -> list[dict]:
        """Reservoir-sample n events from the current window contents."""
        return reservoir_sample(list(self._buf), n)

    def __len__(self) -> int:
        return len(self._buf)


def _load_new_events(
    stream_path: str,
    file_line_counts: dict[str, int],
) -> list[dict]:
    """
    Load only lines that have been appended to files since the last call.

    Tracks the number of lines already read per file (not mtime), so:
    - Files that have grown get their new lines read.
    - Files that haven't changed are skipped cheaply.
    - Rotated / replaced files (line count drops) are re-read in full.

    Returns a flat list of successfully parsed event dicts.
    """
    folder = Path(stream_path)
    files = sorted(
        f for f in folder.rglob("*")
        if f.suffix in (".ndjson", ".json") and f.is_file()
    )
    new_events: list[dict] = []

    for file_path in files:
        key = str(file_path)
        prev_count = file_line_counts.get(key, 0)
        try:
            with open(file_path, encoding="utf-8") as fh:
                all_lines = fh.readlines()
        except OSError:
            continue

        current_count = len(all_lines)
        if current_count < prev_count:
            # File was truncated / rotated — read from the top
            prev_count = 0

        if current_count <= prev_count:
            continue  # nothing new

        for line in all_lines[prev_count:]:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                ev = _json.loads(stripped)
                if isinstance(ev, dict):
                    new_events.append(ev)
            except _json.JSONDecodeError:
                pass

        file_line_counts[key] = current_count

    return new_events


# ---------------------------------------------------------------------------
# P1-B — Window checkpoint (restart / failover recovery)
# ---------------------------------------------------------------------------

def _write_poll_state(schema_dir: Path, sampled: int, window_size: int, new_events: int) -> None:
    """
    Write a small JSON file after every watch poll so the UI can show
    accurate last-polled time and sample counts.

    File: <schema_dir>/.watch_state/last_polled.json
    Contents: {ts, sampled, window_size, new_events}
    """
    try:
        state_dir = schema_dir / ".watch_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "ts": datetime.now(UTC).isoformat(),
            "sampled": sampled,
            "window_size": window_size,
            "new_events": new_events,
        }
        (state_dir / "last_polled.json").write_text(_json.dumps(state))
    except OSError as e:
        logger.warning("Could not write poll state: %s", e)


def _save_checkpoint(window: EventWindow, checkpoint_path: Path) -> None:
    """
    Persist the rolling window contents to disk as NDJSON.

    Called after every successful poll cycle.  The file is overwritten in full
    (not appended) so it always reflects the current window state.  If writing
    fails (permissions, disk full) it logs a warning and continues — a stale or
    missing checkpoint is safe; the watcher will simply reseed from stream files.
    """
    try:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_path, "w", encoding="utf-8") as fh:
            for event in window._buf:
                fh.write(_json.dumps(event) + "\n")
        logger.debug("Checkpoint saved: %d events → %s", len(window), checkpoint_path)
    except OSError as e:
        logger.warning("Could not save window checkpoint (%s): %s", checkpoint_path, e)


def _load_checkpoint(checkpoint_path: Path) -> list[dict]:
    """
    Load window events from a checkpoint file written by _save_checkpoint.

    Returns an empty list when the file doesn't exist or can't be read.
    Malformed lines are silently skipped — a partially-corrupt checkpoint is
    better than crashing: the watcher will fill in missing events on the next
    poll from the live stream files.
    """
    if not checkpoint_path.exists():
        return []
    events: list[dict] = []
    try:
        with open(checkpoint_path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    ev = _json.loads(stripped)
                    if isinstance(ev, dict):
                        events.append(ev)
                except _json.JSONDecodeError:
                    pass
        logger.info("Loaded %d events from checkpoint: %s", len(events), checkpoint_path)
    except OSError as e:
        logger.warning("Could not read window checkpoint (%s): %s", checkpoint_path, e)
    return events


# ---------------------------------------------------------------------------
# P1-A — Multi-schema drift detection
# ---------------------------------------------------------------------------

# Type fields checked (in order) when routing events to clusters.
# Mirrors the profiler's _TYPE_FIELDS list.
_TYPE_FIELDS = ("type", "event_type", "schema", "kind", "_type", "record_type", "msg_type")



def _route_event_to_cluster(event: dict, profile: dict) -> str | None:
    """
    Assign one event to a cluster_id.

    Routing strategy (in priority order):
    1. If profile.yaml contains an explicit routing_field (written since this fix
       was introduced), look up that field's value directly — O(1), no hashing.
    2. For structural_fingerprint streams (routing_field is None): recompute the
       structural key hash — same algorithm as the profiler.
    3. Backward-compat scan: for profiles written before routing_field existed,
       scan _TYPE_FIELDS in order and return the first match.

    Returns None when the event doesn't match any known cluster (new event family).
    """
    import hashlib

    known = {sub["cluster_id"] for sub in profile.get("sub_schemas", [])}
    visible = {k: v for k, v in event.items() if not k.startswith("_")}

    routing_field: str | None = profile.get("routing_field")  # None if not set or structural

    if routing_field is not None:
        # Fix 1: explicit routing field — read directly, no scanning needed.
        val = visible.get(routing_field)
        if isinstance(val, str) and val.strip() in known:
            return val.strip()
        # Field present but value not in known clusters → new event family.
        # Don't fall through to structural hash for event_type_field streams.
        return None

    # routing_field is None → structural fingerprint or legacy profile.yaml.

    # Try _TYPE_FIELDS scan for legacy profiles (written before routing_field existed).
    for field in _TYPE_FIELDS:
        val = visible.get(field)
        if isinstance(val, str) and val.strip() and val.strip() in known:
            return val.strip()

    # Structural fingerprint: recompute hash of sorted top-level key names.
    if len(visible) >= 2:
        key_sig = "|".join(sorted(str(k) for k in visible))
        h = hashlib.md5(key_sig.encode()).hexdigest()[:8]
        candidate = f"struct:{h}"
        if candidate in known:
            return candidate

    return None  # no known cluster matches → new event family


def _sub_schema_to_inferred_schema(cluster: dict, stream_name: str) -> InferredSchema:
    """
    Convert a single sub-schema dict (from profile.yaml) into an InferredSchema
    so it can be passed to the existing detect_drift() function.
    """
    fields = []
    for fd in cluster.get("fields", []):
        from .models import PIICategory as _PII
        fields.append(FieldSchema(
            name=fd["path"].split(".")[-1],
            path=fd["path"],
            field_type=FieldType(fd["type"]),
            nullable=fd.get("nullable", False),
            required=fd.get("required", True),
            presence_rate=fd.get("presence_rate", 1.0),
            enum_values=fd.get("enum_values"),
            pii_categories=[_PII(p) for p in fd.get("pii", [])],
            confidence=fd.get("confidence", 1.0),
            notes=fd.get("notes"),
        ))

    return InferredSchema(
        stream_name=f"{stream_name}/{cluster['cluster_id']}",
        version="1.0.0",
        inferred_at=cluster.get("profiled_at", ""),
        event_count_sampled=cluster.get("event_count", 0),
        fields=fields,
        inference_model="profile.yaml",
        inference_confidence=cluster.get("inference_confidence", 1.0),
    )


def detect_drift_multi_schema(
    profile: dict,
    new_sample: list[dict],
    stream_name: str,
    *,
    warmup: bool = False,
    stability_cfg=None,  # StabilityConfig | None
) -> list[DriftReport]:
    """
    Run per-cluster drift detection using the full profile.yaml.

    For each sub-schema in the profile:
      1. Route matching events from new_sample to this cluster.
      2. Run detect_drift() against the cluster's baseline schema.
      3. Tag every FieldDrift with cluster_id.

    Also detects new event families: events that match no known cluster and
    exceed 5% of the sample trigger a Tier-2 drift report.

    Returns a list of DriftReports — one per affected cluster (plus one for
    unknown events if applicable).  Returns an empty list when all clusters
    are clean.
    """
    sub_schemas = profile.get("sub_schemas", [])
    if not sub_schemas:
        return []

    # Warmup guard: accumulate window but suppress all alerts during grace period
    if warmup:
        return []

    # Route each event to a cluster
    cluster_buckets: dict[str, list[dict]] = {s["cluster_id"]: [] for s in sub_schemas}
    unknown: list[dict] = []

    for event in new_sample:
        cid = _route_event_to_cluster(event, profile)
        if cid is not None:
            cluster_buckets[cid].append(event)
        else:
            unknown.append(event)

    reports: list[DriftReport] = []
    now = datetime.now(UTC).isoformat()

    for cluster in sub_schemas:
        cid = cluster["cluster_id"]
        cluster_events = cluster_buckets[cid]
        baseline_rate = cluster.get("sample_rate", 0.0)

        # ── Cluster routing regression (Fix 3) ────────────────────────────────
        # A cluster that was significant at init time (≥10% of stream) but
        # receives zero events in a large-enough sample is a first-class signal:
        # the routing field may have been renamed, the event type deprecated, or
        # the producer configuration changed.  Distinct from a new_cluster event
        # (that is about events appearing; this is about events disappearing).
        _REGRESSION_MIN_BASELINE = 0.10   # cluster must have been ≥10% at init
        _REGRESSION_MIN_SAMPLE = 30       # sample must be large enough to trust
        if (
            baseline_rate >= _REGRESSION_MIN_BASELINE
            and len(cluster_events) == 0
            and len(new_sample) >= _REGRESSION_MIN_SAMPLE
        ):
            regression_drift = FieldDrift(
                field_path="__cluster__",
                drift_type="cluster_routing_regression",
                cluster_id=cid,
                previous_presence_rate=baseline_rate,
                observed_presence_rate=0.0,
                affected_event_rate=baseline_rate,
                tier=DriftTier.TIER_2,
                auto_correctable=False,
                proposed_correction=(
                    f"Cluster '{cid}' accounted for {baseline_rate:.0%} of events at "
                    f"init time but received 0 events in the current sample of "
                    f"{len(new_sample)}. Likely causes: routing field renamed, "
                    f"event_type value changed, or producer stopped. "
                    f"Run 'streamforge init' to rediscover clusters."
                ),
            )
            reports.append(DriftReport(
                stream_name=stream_name,
                detected_at=now,
                schema_version="profile.yaml",
                events_sampled=len(new_sample),
                drifts=[regression_drift],
                highest_tier=DriftTier.TIER_2,
                summary=(
                    f"Cluster routing regression: '{cid}' (baseline {baseline_rate:.0%} "
                    f"of stream) received no events — routing metadata may be stale."
                ),
            ))
            continue  # nothing to drift-check without events

        # ── Partial routing regression ─────────────────────────────────────────
        # A cluster that receives significantly fewer events than expected at init
        # may indicate imprecise routing boundaries or a partially deprecated event type.
        # Only fire when the relative drop exceeds _routing_regression_floor() AND
        # the cluster has enough events to distinguish a real rate drop from noise.
        if (
            baseline_rate >= _REGRESSION_MIN_BASELINE
            and len(new_sample) >= _REGRESSION_MIN_SAMPLE
            and len(cluster_events) >= _REGRESSION_MIN_SAMPLE
        ):
            observed_rate = len(cluster_events) / len(new_sample)
            if observed_rate < baseline_rate:
                relative_drop = (baseline_rate - observed_rate) / baseline_rate
                if relative_drop >= _routing_regression_floor():
                    partial_drift = FieldDrift(
                        field_path="__cluster__",
                        drift_type="cluster_routing_regression",
                        cluster_id=cid,
                        previous_presence_rate=baseline_rate,
                        observed_presence_rate=round(observed_rate, 4),
                        affected_event_rate=round(relative_drop, 4),
                        tier=DriftTier.TIER_2,
                        auto_correctable=False,
                        proposed_correction=(
                            f"Cluster '{cid}' expected {baseline_rate:.0%} of events "
                            f"but received only {observed_rate:.0%} ({relative_drop:.0%} relative drop). "
                            f"Possible causes: imprecise cluster boundary, event type partially renamed, "
                            f"or reduced producer throughput. Consider re-running 'streamforge init'."
                        ),
                    )
                    reports.append(DriftReport(
                        stream_name=stream_name,
                        detected_at=now,
                        schema_version="profile.yaml",
                        events_sampled=len(new_sample),
                        drifts=[partial_drift],
                        highest_tier=DriftTier.TIER_2,
                        summary=(
                            f"Partial cluster routing regression: '{cid}' received "
                            f"{observed_rate:.0%} of events (baseline {baseline_rate:.0%}, "
                            f"{relative_drop:.0%} relative drop)."
                        ),
                    ))

        if len(cluster_events) < MIN_CLUSTER_EVENTS_FOR_DRIFT:
            # Under-sampled in this poll window — below the statistical threshold
            # for reliable drift detection.  Skip rather than fire false alerts.
            # This is distinct from cluster_routing_regression (which requires
            # zero events AND a large-enough total sample).
            logger.debug(
                "cluster %s: only %d events in sample — skipping drift check "
                "(need ≥%d; consider increasing --sample-size or preseed count)",
                cid, len(cluster_events), MIN_CLUSTER_EVENTS_FOR_DRIFT,
            )
            continue

        sub = _sub_schema_to_inferred_schema(cluster, stream_name)
        report = detect_drift(sub, cluster_events, stream_name, stability_cfg=stability_cfg)
        if report is None:
            continue

        # Tag every drift with the cluster it came from
        for d in report.drifts:
            d.cluster_id = cid

        reports.append(report)

    # ── New event families ────────────────────────────────────────────────────
    # Events that match no known cluster and exceed 5% of the sample indicate
    # a new event type has appeared.  "new_cluster" semantics: something added.
    # Contrast with "cluster_routing_regression": something disappeared.
    unknown_rate = len(unknown) / max(len(new_sample), 1)
    _nc_threshold = (
        stability_cfg.new_cluster_threshold
        if stability_cfg is not None and hasattr(stability_cfg, "new_cluster_threshold")
        else _new_cluster_threshold()
    )
    if unknown_rate >= _nc_threshold:
        new_family_drift = FieldDrift(
            field_path="__cluster__",
            drift_type="new_cluster",
            affected_event_rate=unknown_rate,
            tier=DriftTier.TIER_2,
            auto_correctable=False,
            proposed_correction=(
                f"{len(unknown)} events ({unknown_rate:.0%}) do not match any known "
                f"sub-schema. Run 'streamforge init' to rediscover clusters."
            ),
        )
        new_family_drift.drift_class = classify_drift_class(new_family_drift, stability_cfg)
        evolution_count = 1 if new_family_drift.drift_class == DriftClass.EVOLUTION else 0
        noise_count = 1 if new_family_drift.drift_class == DriftClass.NOISE else 0
        reports.append(DriftReport(
            stream_name=stream_name,
            detected_at=now,
            schema_version="profile.yaml",
            events_sampled=len(new_sample),
            drifts=[new_family_drift],
            highest_tier=DriftTier.TIER_2,
            summary=(
                f"{unknown_rate:.0%} of sampled events ({len(unknown)}) match no known "
                f"cluster — new event family may have been introduced."
            ),
            evolution_count=evolution_count,
            noise_count=noise_count,
        ))

    return reports


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
    from .report_writer import write_drift_report

    now_str = datetime.now().strftime("%H:%M:%S")
    stream_label = report.stream_name
    tier_label = f"Tier {report.highest_tier.value}"
    emoji = "🔴" if report.highest_tier == DriftTier.TIER_3 else "⚠"
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
            f"           → {d.field_path}{cid_note}: {d.drift_type} "
            f"({d.affected_event_rate:.0%} of events) [Tier {d.tier.value}]"
        )

    report_path = write_drift_report(report, str(drift_output_dir))
    print(f"           → Report: {report_path}")

    if webhook_url:
        post_webhook(report, webhook_url)


def watch_stream(
    stream_path: str,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    window_capacity: int = 2000,
    webhook_url: str | None = None,
) -> None:
    """
    Main watch loop. Runs until Ctrl+C.

    P1-B fix: accumulates events in a rolling EventWindow (default 2000 events)
    and samples drift candidates from the full window rather than only the
    latest batch.  This makes slow drift (field presence fading over hours)
    detectable and ensures each drift check has a statistically stable sample.

    P1-A fix: if a profile.yaml exists alongside schema.yaml, routes events to
    their sub-schema clusters and runs per-cluster drift detection.
    """
    from .schema_writer import load_profile, load_schema

    schema_dir = Path(schema_path).parent
    profile = load_profile(schema_dir)
    multi_schema = profile is not None and len(profile.get("sub_schemas", [])) > 1

    # Fix 4 — canonical contract: when profile.yaml exists, the primary sub-schema
    # is the authoritative baseline.  Rebuilding it from profile avoids silent
    # divergence when schema.yaml has been manually edited since the last init.
    if multi_schema:
        baseline = _sub_schema_to_inferred_schema(profile["sub_schemas"][0], "")
        # Use the stream name from schema.yaml for consistent naming
        baseline.stream_name = load_schema(schema_path).stream_name
    else:
        baseline = load_schema(schema_path)

    stream_name = baseline.stream_name
    drift_output_dir = Path("drift_reports")

    mode_note = (
        f"multi-schema ({len(profile['sub_schemas'])} clusters, "
        f"routing_field={profile.get('routing_field') or 'structural'})"
        if multi_schema else "single-schema"
    )

    # Checkpoint path — persists the rolling window across restarts
    checkpoint_path = schema_dir / ".watch_state" / "window.ndjson"

    logger.info(
        "Watching %s every %ds (schema: %s, mode: %s, window: %d, checkpoint: %s)",
        stream_path, poll_interval_seconds, schema_path, mode_note, window_capacity, checkpoint_path,
    )
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Watching {stream_name} — {mode_note} — "
        f"window={window_capacity} events"
    )

    from .models import DriftIncident, DriftIncidentStatus
    from .schema_writer import load_drift_state, save_drift_state
    from .watch_state import WatchState as _WatchState

    # Load (or create) persistent watch state — survives restarts
    _wstate = _WatchState.load(stream_name)
    if _wstate.phase == "STABLE":
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABLE phase (stable since {_wstate.stable_since or 'unknown'})"
        )
    elif _wstate.phase == "STABILIZING":
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABILIZING phase "
            f"({_wstate.stability_clean_count}/3 clean cycles)"
        )
    else:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Phase: LEARNING — {_wstate.warmup_remaining} observation cycle(s) before stabilization check"
        )

    window = EventWindow(capacity=window_capacity)
    file_line_counts: dict[str, int] = {}
    # Tracks drift fingerprints already reported this session.
    # A fingerprint is (cluster_id_or_none, field_path, drift_type).
    # We only write a new report when a fingerprint is *newly* detected;
    # re-detecting the same drift in the next poll is silently suppressed.
    # Fingerprints are cleared when the drift stops being detected.
    # On startup we seed from any open incidents in drift_state.yaml so
    # restarting watch doesn't re-fire incidents that were already reported.
    state = load_drift_state(schema_dir)
    active_drift_sigs: set[tuple[str | None, str, str]] = {
        (inc.cluster_id, inc.field_path, inc.drift_type)
        for inc in state.incidents
        if inc.status == DriftIncidentStatus.OPEN
    }

    # Fix 2 — restore window from checkpoint if available (restart recovery)
    checkpoint_events = _load_checkpoint(checkpoint_path)
    if checkpoint_events:
        window.add(checkpoint_events)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Restored {len(checkpoint_events)} events from checkpoint"
        )

    # Seed the window with all existing events on first run (augments or
    # replaces checkpoint — deque evicts oldest automatically)
    initial = load_events_from_folder(stream_path)
    if initial:
        window.add(initial)
        # Populate line counts so subsequent polls only read new lines
        for f in sorted(
            p for p in Path(stream_path).rglob("*")
            if p.suffix in (".ndjson", ".json") and p.is_file()
        ):
            try:
                with open(f, encoding="utf-8") as fh:
                    file_line_counts[str(f)] = sum(1 for _ in fh)
            except OSError:
                pass

    try:
        while True:
            # Load only newly appended lines (P1-B: track by line count, not mtime)
            new_events = _load_new_events(stream_path, file_line_counts)
            if new_events:
                window.add(new_events)

            now_str = datetime.now().strftime("%H:%M:%S")

            if len(window) < 10:
                print(f"[{now_str}] ○ {stream_name} — warming up ({len(window)} events in window)")
                time.sleep(poll_interval_seconds)
                continue

            # Advance warmup counter (file-based loop uses simple cycle count)
            _wstate.tick_warmup()

            sample = window.sample(sample_size)

            all_detected: list[FieldDrift] = []
            if multi_schema:
                reports = detect_drift_multi_schema(profile, sample, stream_name)
                for report in reports:
                    all_detected.extend(report.drifts)
            else:
                single_report = detect_drift(baseline, sample, stream_name)
                if single_report:
                    all_detected = single_report.drifts

            # During LEARNING phase: suppress non-critical drift alerts
            if _wstate.is_learning and all_detected:
                _critical_in_learning = [d for d in all_detected if d.tier == DriftTier.TIER_3]
                if not _critical_in_learning:
                    _sig_count = len(all_detected)
                    print(
                        f"[{now_str}] ○ {stream_name} — LEARNING "
                        f"({_wstate.warmup_remaining} cycle(s) remaining, "
                        f"{_sig_count} signal(s) observed — suppressed)"
                    )
                    _wstate.save()
                    time.sleep(poll_interval_seconds)
                    continue
                # Critical drifts are never suppressed even during LEARNING

            current_sigs: set[tuple[str | None, str, str]] = {
                (d.cluster_id, d.field_path, d.drift_type) for d in all_detected
            }

            # Reload drift state — may have been updated by 'streamforge accept' externally
            state = load_drift_state(schema_dir)
            now_iso = datetime.now(UTC).isoformat()

            # Determine which signatures are actively suppressed or already accepted
            non_actionable: set[tuple[str | None, str, str]] = {
                (inc.cluster_id, inc.field_path, inc.drift_type)
                for inc in state.incidents
                if inc.status in (DriftIncidentStatus.ACCEPTED, DriftIncidentStatus.SUPPRESSED)
            }

            new_sigs = current_sigs - active_drift_sigs - non_actionable
            cleared_sigs = active_drift_sigs - current_sigs

            # Create incidents for newly detected drifts
            new_incidents: list[DriftIncident] = []
            new_drifts_to_report: list[FieldDrift] = []
            for d in all_detected:
                sig = (d.cluster_id, d.field_path, d.drift_type)
                if sig not in new_sigs:
                    continue
                inc_id = (
                    f"drift-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
                    f"-{d.field_path.replace('.', '_')}"
                    f"{('-' + d.cluster_id) if d.cluster_id else ''}"
                )
                new_incidents.append(DriftIncident(
                    id=inc_id,
                    field_path=d.field_path,
                    cluster_id=d.cluster_id,
                    drift_type=d.drift_type,
                    tier=d.tier.value,
                    first_detected=now_iso,
                    last_seen=now_iso,
                    occurrences=1,
                    status=DriftIncidentStatus.OPEN,
                ))
                new_drifts_to_report.append(d)

            # Update occurrences + last_seen for ongoing open incidents
            updated_incidents = []
            for inc in state.incidents:
                sig = (inc.cluster_id, inc.field_path, inc.drift_type)
                if inc.status == DriftIncidentStatus.OPEN and sig in current_sigs:
                    inc = inc.model_copy(update={"last_seen": now_iso, "occurrences": inc.occurrences + 1})
                elif inc.status == DriftIncidentStatus.OPEN and sig in cleared_sigs:
                    inc = inc.model_copy(update={
                        "status": DriftIncidentStatus.RESOLVED,
                        "resolved_at": now_iso,
                        "resolution_note": "Drift cleared — no longer detected in sample",
                    })
                updated_incidents.append(inc)
            updated_incidents.extend(new_incidents)
            save_drift_state(schema_dir, state.model_copy(update={"incidents": updated_incidents}))

            # Print to console and write report file for new drifts only
            if new_drifts_to_report:
                if multi_schema:
                    # Re-group new drifts by their original report
                    for report in reports:  # type: ignore[possibly-undefined]
                        relevant = [d for d in new_drifts_to_report if d in report.drifts]
                        if relevant:
                            filtered = report.model_copy(update={
                                "drifts": relevant,
                                "highest_tier": max(d.tier for d in relevant),
                            })
                            _print_drift_report(filtered, drift_output_dir, webhook_url)
                else:
                    assert single_report is not None  # type: ignore[possibly-undefined]
                    filtered = single_report.model_copy(update={
                        "drifts": new_drifts_to_report,
                        "highest_tier": max(d.tier for d in new_drifts_to_report),
                    })
                    _print_drift_report(filtered, drift_output_dir, webhook_url)
            elif current_sigs and not new_sigs:
                ongoing_count = len([
                    inc for inc in updated_incidents
                    if inc.status == DriftIncidentStatus.OPEN
                ])
                print(
                    f"[{now_str}] ~ {stream_name} — "
                    f"{len(sample)} sampled / {len(window)} in window — "
                    f"{ongoing_count} open incident(s) — run `streamforge status` or `streamforge accept`"
                )
            else:
                label = "all clusters clean" if multi_schema else "schema clean"
                print(
                    f"[{now_str}] ✓ {stream_name} — "
                    f"{len(sample)} sampled / {len(window)} in window — {label}"
                )

            active_drift_sigs = current_sigs - non_actionable

            # Update WatchState phase machine
            if new_drifts_to_report:
                _wstate.mark_drift()
            else:
                _wstate.mark_clean()
            _wstate.save()

            # Fix 2 — save window checkpoint after each successful poll
            _save_checkpoint(window, checkpoint_path)

            # Write last-polled state for the UI (last event timestamp + sample counts)
            _write_poll_state(schema_dir, len(sample), len(window), len(new_events))

            time.sleep(poll_interval_seconds)

    except KeyboardInterrupt:
        # Save one last checkpoint before exiting so the next restart picks up
        # roughly where this session left off
        _save_checkpoint(window, checkpoint_path)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Watch stopped.")


# ---------------------------------------------------------------------------
# Kafka-backed watch loop
# ---------------------------------------------------------------------------

async def _watch_kafka_async(
    topic: str,
    kafka_cfg: Any,
    schema_path: str,
    poll_interval_seconds: int,
    sample_size: int,
    window_capacity: int,
    webhook_url: str | None,
) -> None:
    """
    Async Kafka watch loop — runs inside asyncio.run() from watch_stream_kafka().

    Uses KafkaConnector.read_batch() + ack() instead of file polling.
    The read_batch timeout IS the poll interval — no extra sleep needed.
    Committed Kafka offsets are the primary recovery mechanism; the NDJSON
    checkpoint pre-seeds the EventWindow on restart (warm-start optimisation).
    """
    from .connectors.kafka import KafkaConnector
    from .schema_writer import load_profile, load_schema

    schema_dir = Path(schema_path).parent
    profile = load_profile(schema_dir)
    multi_schema = profile is not None and len(profile.get("sub_schemas", [])) > 1

    if multi_schema:
        baseline = _sub_schema_to_inferred_schema(profile["sub_schemas"][0], "")
        baseline.stream_name = load_schema(schema_path).stream_name
    else:
        baseline = load_schema(schema_path)

    stream_name = baseline.stream_name
    drift_output_dir = Path("drift_reports")
    checkpoint_path = schema_dir / ".watch_state" / "window.ndjson"

    mode_note = (
        f"multi-schema ({len(profile['sub_schemas'])} clusters, "
        f"routing_field={profile.get('routing_field') or 'structural'})"
        if multi_schema else "single-schema"
    )

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Watching kafka://{topic} — {mode_note} — "
        f"window={window_capacity} events"
    )

    window = EventWindow(capacity=window_capacity)

    # ── Stability state machine ────────────────────────────────────────────────
    # Phase 1 LEARNING:     observe N cycles, no alerts (even Tier-1/2).
    #                       Tier-3 always alerts immediately (data integrity risk).
    # Phase 2 STABILIZING:  require M consecutive clean cycles before declaring stable.
    #                       Resets if Tier-2+ drift appears during this phase.
    # Phase 3 STABLE:       full alerting on. Tier-1/2 requires K consecutive drift
    #                       cycles before alerting (suppresses flapping / rollout noise).
    #                       Tier-3 always alerts immediately.
    #
    # Configurable via env:
    #   STREAMFORGE_WARMUP_CYCLES            default 10  (Phase 1 length)
    #   STREAMFORGE_STABILITY_CYCLES         default 3   (Phase 2 consecutive-clean needed)
    #   STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD default 2 (Phase 3 flap suppression)
    #
    # State is persisted in schemas/<stream>/.watch_state.json so restarts
    # resume from the correct phase rather than resetting to LEARNING.

    # Stability parameters: prefer TopicConfig.stability, fall back to env vars
    # (env var fallback keeps backward-compat for GCP deployments without config/).
    _tc = None
    try:
        from .topic_config import load_topic_config as _load_tc
        _tc = _load_tc(topic)
        _stab = getattr(_tc, "stability", None)
    except Exception:
        _stab = None

    _warmup_total = (
        _stab.warmup_cycles if _stab else
        int(os.environ.get("STREAMFORGE_WARMUP_CYCLES", "10"))
    )
    _stability_needed = (
        _stab.stability_cycles if _stab else
        int(os.environ.get("STREAMFORGE_STABILITY_CYCLES", "3"))
    )
    _consec_threshold = (
        _stab.consecutive_drift_threshold if _stab else
        int(os.environ.get("STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD", "2"))
    )

    # Load persistent watch state via WatchState (migrating legacy .watch_state.json if present)
    from .watch_state import WatchState as _WatchState
    _legacy_state_file = schema_dir / ".watch_state.json"
    _kws = (
        _WatchState.migrate_legacy(topic, _legacy_state_file)
        or _WatchState.load(topic)
    )
    # Sync warmup_remaining with configured warmup total on first load
    if not _kws.warmup_done and _kws.cycle_count == 0:
        _kws.warmup_remaining = _warmup_total

    _phase                 = _kws.phase
    _warmup_remaining      = _kws.warmup_remaining
    _stability_clean_count = _kws.stability_clean_count
    _consec_drift_count    = _kws.consecutive_drifts

    def _save_watch_state_kws() -> None:
        _kws.phase = _phase
        _kws.warmup_remaining = _warmup_remaining
        _kws.stability_clean_count = _stability_clean_count
        _kws.consecutive_drifts = _consec_drift_count
        _kws.save()

    def _mark_stable(state: dict) -> None:
        nonlocal _phase
        _phase = "STABLE"
        _kws.phase = "STABLE"
        _kws.stable_since = datetime.now().isoformat()
        _kws.save()
        stable_file = schema_dir / ".stable"
        stable_file.write_text(
            f"stable_since: {_kws.stable_since}\n"
            f"warmup_cycles: {_warmup_total}\n"
            f"stability_cycles: {_stability_needed}\n"
        )
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"✅ {stream_name} — SYSTEM STABLE — full drift alerting now active"
        )

    if _phase == "STABLE":
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABLE phase (stable since {_kws.stable_since or 'unknown'})"
        )
    elif _phase == "STABILIZING":
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Resumed in STABILIZING phase ({_stability_clean_count}/{_stability_needed} clean cycles)"
        )
    else:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Phase: LEARNING — {_warmup_remaining} observation cycle(s) before stabilization check"
        )

    # Warm-start: restore rolling window from previous checkpoint
    checkpoint_events = _load_checkpoint(checkpoint_path)
    if checkpoint_events:
        window.add(checkpoint_events)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Restored {len(checkpoint_events)} events from checkpoint"
        )

    # Use "latest" offset reset for watch — only care about new events.
    # The checkpoint pre-seeds the window so drift detection starts immediately.
    kafka_cfg.auto_offset_reset = "latest"
    kafka_cfg.consumer_group = "streamforge-watcher"

    try:
        async with KafkaConnector(topic, kafka_cfg) as conn:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Connected: {conn.source_id}"
            )
            while True:
                # Poll for up to poll_interval_seconds — the timeout IS the interval
                batch = await conn.read_batch(
                    max_messages=kafka_cfg.max_poll_records,
                    timeout_ms=poll_interval_seconds * 1_000,
                )

                if batch:
                    window.add(batch)
                    await conn.ack()  # commit offsets after adding to window

                now_str = datetime.now().strftime("%H:%M:%S")

                if len(window) < 10:
                    print(f"[{now_str}] ○ {stream_name} — warming up ({len(window)} events in window)")
                    continue

                sample = window.sample(sample_size)

                # ── Phase 1: LEARNING ──────────────────────────────────────────
                if _phase == "LEARNING":
                    _warmup_remaining -= 1
                    # Run detection only to catch Tier-3 (critical) even in learning
                    _learning_reports = (
                        detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                        if multi_schema
                        else ([r] if (r := detect_drift(baseline, sample, stream_name)) else [])
                    )
                    _critical = [r for r in _learning_reports if r.highest_tier == DriftTier.TIER_3]
                    if _critical:
                        for report in _critical:
                            print(
                                f"[{now_str}] 🔴 {stream_name} — TIER-3 CRITICAL during LEARNING "
                                f"— alerting immediately (data integrity risk)"
                            )
                            _print_drift_report(report, drift_output_dir, webhook_url)
                    else:
                        _non_critical_count = sum(len(r.drifts) for r in _learning_reports)
                        _observed_note = (
                            f", {_non_critical_count} signal(s) observed (suppressed)"
                            if _non_critical_count else ""
                        )
                        print(
                            f"[{now_str}] ○ {stream_name} — LEARNING "
                            f"({_warmup_remaining} cycle(s) remaining, "
                            f"{len(window)} in window{_observed_note})"
                        )

                    if _warmup_remaining <= 0:
                        _phase = "STABILIZING"
                        _stability_clean_count = 0
                        print(
                            f"[{now_str}] {stream_name} — LEARNING complete → entering STABILIZING phase "
                            f"(need {_stability_needed} consecutive clean cycles)"
                        )

                    _save_watch_state_kws()
                    _save_checkpoint(window, checkpoint_path)
                    _write_poll_state(schema_dir, len(sample), len(window), len(batch))
                    continue

                # ── Phase 2: STABILIZING ───────────────────────────────────────
                if _phase == "STABILIZING":
                    _stab_reports = (
                        detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                        if multi_schema
                        else ([r] if (r := detect_drift(baseline, sample, stream_name)) else [])
                    )
                    _critical = [r for r in _stab_reports if r.highest_tier == DriftTier.TIER_3]
                    _significant = [r for r in _stab_reports if r.highest_tier >= DriftTier.TIER_2]

                    if _critical:
                        for report in _critical:
                            print(
                                f"[{now_str}] 🔴 {stream_name} — TIER-3 CRITICAL during STABILIZING "
                                f"— alerting immediately"
                            )
                            _print_drift_report(report, drift_output_dir, webhook_url)
                        # Reset stability clock on critical drift
                        _stability_clean_count = 0
                    elif _significant:
                        print(
                            f"[{now_str}] ⚡ {stream_name} — STABILIZING — Tier-2 drift observed, "
                            f"resetting clean-cycle counter (was {_stability_clean_count}/{_stability_needed})"
                        )
                        _stability_clean_count = 0
                    else:
                        _stability_clean_count += 1
                        print(
                            f"[{now_str}] ○ {stream_name} — STABILIZING "
                            f"({_stability_clean_count}/{_stability_needed} clean cycles, "
                            f"{len(window)} in window)"
                        )
                        if _stability_clean_count >= _stability_needed:
                            _mark_stable({})
                            _phase = "STABLE"
                            _consec_drift_count = 0

                    _save_watch_state_kws()
                    _save_checkpoint(window, checkpoint_path)
                    _write_poll_state(schema_dir, len(sample), len(window), len(batch))
                    continue

                # ── Phase 3: STABLE ────────────────────────────────────────────
                if multi_schema:
                    reports = detect_drift_multi_schema(profile, sample, stream_name, stability_cfg=_stab)
                else:
                    _r = detect_drift(baseline, sample, stream_name)
                    reports = [_r] if _r else []

                if not reports:
                    _consec_drift_count = 0
                    print(
                        f"[{now_str}] ✓ {stream_name} — "
                        f"{len(sample)} sampled / {len(window)} in window — all clusters clean"
                    )
                else:
                    # Split each report's drifts by drift_class before routing.
                    # Build a DRIFT-only view for the alert path and collect
                    # evolution / noise signals for their respective handlers.
                    _drift_reports: list[DriftReport] = []
                    _evolution_drifts: list[FieldDrift] = []
                    _noise_count = 0

                    for report in reports:
                        _rd = [d for d in report.drifts if d.drift_class == DriftClass.DRIFT]
                        _re = [d for d in report.drifts if d.drift_class == DriftClass.EVOLUTION]
                        _rn = [d for d in report.drifts if d.drift_class == DriftClass.NOISE]

                        _evolution_drifts.extend(_re)
                        _noise_count += len(_rn)

                        if _rd:
                            _drift_reports.append(
                                report.model_copy(update={
                                    "drifts": _rd,
                                    "highest_tier": max(d.tier for d in _rd),
                                    "evolution_count": 0,
                                    "noise_count": len(_rn),
                                })
                            )

                    # EVOLUTION → evolution handler (no alert)
                    if _evolution_drifts:
                        _handle_evolution(_evolution_drifts, stream_name, schema_dir, _tc)

                    # NOISE → suppress (debug log only)
                    if _noise_count:
                        logger.debug(
                            "[%s] %s — %d noise signal(s) suppressed",
                            now_str, stream_name, _noise_count,
                        )

                    # DRIFT → existing alert path (tier-based flap suppression)
                    _critical = [r for r in _drift_reports if r.highest_tier == DriftTier.TIER_3]
                    _non_critical = [r for r in _drift_reports if r.highest_tier < DriftTier.TIER_3]

                    # Tier-3: always alert immediately
                    for report in _critical:
                        _consec_drift_count = 0  # critical resets flap counter
                        _print_drift_report(report, drift_output_dir, webhook_url)

                    # Tier-1/2: only alert after K consecutive drift cycles
                    if _non_critical:
                        _consec_drift_count += 1
                        if _consec_drift_count >= _consec_threshold:
                            for report in _non_critical:
                                _print_drift_report(report, drift_output_dir, webhook_url)
                        else:
                            _total_drifts = sum(len(r.drifts) for r in _non_critical)
                            print(
                                f"[{now_str}] ○ {stream_name} — {_total_drifts} signal(s) observed "
                                f"(cycle {_consec_drift_count}/{_consec_threshold} — suppressing until sustained)"
                            )

                    # If all signals were evolution/noise (nothing left for DRIFT alert),
                    # and no critical drift fired, treat as clean for the flap counter.
                    if not _critical and not _non_critical:
                        _consec_drift_count = 0

                _save_watch_state_kws()
                _save_checkpoint(window, checkpoint_path)
                _write_poll_state(schema_dir, len(sample), len(window), len(batch))

    except KeyboardInterrupt:
        _save_checkpoint(window, checkpoint_path)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Watch stopped.")


def watch_stream_kafka(
    topic: str,
    kafka_cfg: Any,
    schema_path: str,
    poll_interval_seconds: int = 30,
    sample_size: int = 200,
    window_capacity: int = 2000,
    webhook_url: str | None = None,
) -> None:
    """
    Kafka-backed watch loop. Identical logic to watch_stream() but reads
    from a Kafka topic via KafkaConnector instead of polling NDJSON files.

    This is a thin synchronous wrapper — the real loop runs in asyncio.run()
    so it can use the async KafkaConnector interface cleanly.

    Recovery model:
      Primary:   Kafka committed offsets (via ack() after each batch).
                 On restart the broker serves events from the last committed
                 offset — nothing is missed as long as the topic's retention
                 window covers the outage.
      Secondary: NDJSON window checkpoint at schema_dir/.watch_state/window.ndjson.
                 Pre-seeds the EventWindow so drift detection is immediately
                 statistically meaningful without waiting for 2000+ new events.

    Args:
        topic:                 Kafka topic name (without kafka:// prefix).
        kafka_cfg:             KafkaConfig with broker/auth settings.
        schema_path:           Path to schema.yaml (or profile.yaml directory).
        poll_interval_seconds: How long read_batch() waits for each batch.
        sample_size:           Events to reservoir-sample from the window per tick.
        window_capacity:       Rolling window size (older events evicted first).
        webhook_url:           Optional webhook for drift notifications.
    """
    import asyncio
    import sys

    # Ensure print() output appears immediately even when stdout is redirected
    # to a file (e.g. in demo.sh). Python uses block buffering for non-ttys;
    # reconfigure() switches to line-buffered mode for the duration of watch.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass  # not available in all environments

    asyncio.run(_watch_kafka_async(
        topic, kafka_cfg, schema_path,
        poll_interval_seconds, sample_size, window_capacity, webhook_url,
    ))
