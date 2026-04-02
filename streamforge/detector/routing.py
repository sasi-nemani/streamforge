"""Multi-schema event routing and per-cluster drift detection."""

import logging
import os
from datetime import UTC, datetime

from .. import audit
from ..models import (
    DriftClass,
    DriftReport,
    DriftTier,
    FieldDrift,
    FieldSchema,
    FieldType,
    InferredSchema,
)
from .classify import (
    _new_cluster_threshold,
    _routing_regression_floor,
)
from .core import detect_drift

logger = logging.getLogger(__name__)

# Minimum cluster events in the watch window before drift checks run.
# Clusters with fewer events are skipped with a debug log — they are under-sampled
# in this poll cycle, not necessarily a real routing regression (which requires
# baseline_rate>=10% AND zero events in a >=30-event sample — see below).
MIN_CLUSTER_EVENTS_FOR_DRIFT = int(
    os.environ.get("STREAMFORGE_MIN_CLUSTER_EVENTS_FOR_DRIFT", "200")
)

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
        from ..models import PIICategory as _PII
        pii_validated = []
        for p in fd.get("pii", []):
            try:
                pii_validated.append(_PII(p))
            except ValueError:
                logger.warning("Unknown PII category '%s' in field '%s' — skipping", p, fd.get("path", "?"))
        fields.append(FieldSchema(
            name=fd["path"].split(".")[-1],
            path=fd["path"],
            field_type=FieldType(fd["type"]),
            nullable=fd.get("nullable", False),
            required=fd.get("required", True),
            presence_rate=fd.get("presence_rate", 1.0),
            enum_values=fd.get("enum_values"),
            pii_categories=pii_validated,
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
            audit.log_drift_check(
                field_path="__cluster__",
                check_type="cluster_routing_regression",
                verdict="drift",
                details={"cluster_id": cid, "baseline_rate": baseline_rate,
                         "observed_rate": 0.0, "tier": 2},
                stream=stream_name,
            )
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
                    audit.log_drift_check(
                        field_path="__cluster__",
                        check_type="cluster_routing_regression",
                        verdict="drift",
                        details={"cluster_id": cid, "baseline_rate": baseline_rate,
                                 "observed_rate": round(observed_rate, 4),
                                 "relative_drop": round(relative_drop, 4), "tier": 2},
                        stream=stream_name,
                    )

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
        # Late-bound lookup supports mock.patch on streamforge.drift_detector
        import streamforge.drift_detector as _compat
        new_family_drift.drift_class = _compat.classify_drift_class(new_family_drift, stability_cfg)
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
