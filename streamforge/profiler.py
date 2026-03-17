"""
Sub-schema discovery via structural fingerprinting.

Given a list of events from any stream, discovers clusters of structurally
similar events and groups them. Each cluster gets its own sub-schema inference.

Discovery strategy (in priority order):
  1. Use a known type field (type, event_type, kind, schema, ...) as cluster key
  2. Hash the frozenset of top-level keys as a structural fingerprint
  3. Bucket near-empty events (<2 keys) into _sparse
"""

import hashlib
import logging

logger = logging.getLogger(__name__)

# Fields whose value is used as the cluster key when present
_TYPE_FIELDS = ("type", "event_type", "schema", "kind", "_type", "record_type", "msg_type")


def _cluster_key(event: dict) -> str:
    """
    Compute a cluster key for one event.
    Strips _-prefixed internal metadata before deciding.
    """
    visible = {k: v for k, v in event.items() if not k.startswith("_")}
    if len(visible) < 2:
        return "_sparse"
    for field in _TYPE_FIELDS:
        val = visible.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Structural fingerprint: hash sorted top-level key names
    key_sig = "|".join(sorted(str(k) for k in visible.keys()))
    h = hashlib.md5(key_sig.encode()).hexdigest()[:8]
    return f"struct:{h}"


def _detection_method(clusters: dict) -> str:
    """Infer how clusters were discovered from their keys."""
    meaningful = [k for k in clusters if k not in ("_other", "_sparse")]
    if len(meaningful) <= 1:
        return "single"
    for key in meaningful:
        if not key.startswith("struct:"):
            return "event_type_field"
    return "structural_fingerprint"


def discover_clusters(events: list[dict], min_fraction: float = 0.01) -> dict[str, list[dict]]:
    """
    Group events into clusters by structural fingerprint.

    Clusters with fewer than min_fraction of total events are merged into _other.
    Returns {cluster_id: [events]}, sorted by cluster size descending.
    """
    raw: dict[str, list[dict]] = {}
    for event in events:
        key = _cluster_key(event)
        raw.setdefault(key, []).append(event)

    total = max(len(events), 1)
    min_count = max(1, int(total * min_fraction))

    clusters: dict[str, list[dict]] = {}
    other: list[dict] = []

    for key, evts in sorted(raw.items(), key=lambda x: -len(x[1])):
        # Always keep _sparse; merge small real clusters into _other
        if key == "_sparse" or len(evts) >= min_count:
            clusters[key] = evts
        else:
            other.extend(evts)

    if other:
        clusters["_other"] = other

    method = _detection_method(clusters)
    logger.info("Discovered %d cluster(s) via %s", len(clusters), method)
    for cid, evts in clusters.items():
        logger.info("  %-35s %5d events  (%5.1f%%)", cid, len(evts), 100 * len(evts) / total)

    return clusters


def get_detection_method(clusters: dict) -> str:
    """Public accessor so callers don't need to re-import the private helper."""
    return _detection_method(clusters)
