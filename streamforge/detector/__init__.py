"""streamforge.detector — drift detection package.

Re-exports all public names so ``from streamforge.detector import X`` works
identically to the old ``from streamforge.drift_detector import X``.
"""

from .classify import (
    TIMESTAMP_TYPES,
    TYPE_REFINEMENTS,
    TYPE_WIDENING,
    _handle_evolution,
    _infer_field_type_from_values,
    _new_cluster_threshold,
    _routing_regression_floor,
    classify_drift_class,
    classify_drift_tier,
)
from .core import (
    _MIN_SAMPLE_FOR_STAT,
    _STAT_ALPHA,
    ENUM_DRIFT_THRESHOLD,
    PRESENCE_DRIFT_THRESHOLD,
    TYPE_DRIFT_THRESHOLD,
    detect_drift,
)
from .routing import (
    MIN_CLUSTER_EVENTS_FOR_DRIFT,
    _route_event_to_cluster,
    _sub_schema_to_inferred_schema,
    detect_drift_multi_schema,
)
from .watch import (
    _handle_signal,
    _shutdown,
    _watch_kafka_async,
    watch_stream,
    watch_stream_kafka,
)
from .webhook import (
    _print_drift_report,
    post_webhook,
)
from .window import (
    EventWindow,
    _load_checkpoint,
    _load_new_events,
    _save_checkpoint,
    _write_poll_state,
)

__all__ = [
    # classify.py
    "TIMESTAMP_TYPES",
    "TYPE_REFINEMENTS",
    "TYPE_WIDENING",
    "_new_cluster_threshold",
    "_routing_regression_floor",
    "_infer_field_type_from_values",
    "classify_drift_tier",
    "classify_drift_class",
    "_handle_evolution",
    # core.py
    "TYPE_DRIFT_THRESHOLD",
    "PRESENCE_DRIFT_THRESHOLD",
    "ENUM_DRIFT_THRESHOLD",
    "_STAT_ALPHA",
    "_MIN_SAMPLE_FOR_STAT",
    "detect_drift",
    # window.py
    "EventWindow",
    "_load_new_events",
    "_write_poll_state",
    "_save_checkpoint",
    "_load_checkpoint",
    # routing.py
    "MIN_CLUSTER_EVENTS_FOR_DRIFT",
    "_route_event_to_cluster",
    "_sub_schema_to_inferred_schema",
    "detect_drift_multi_schema",
    # webhook.py
    "post_webhook",
    "_print_drift_report",
    # watch.py
    "watch_stream",
    "watch_stream_kafka",
    "_watch_kafka_async",
    "_handle_signal",
    "_shutdown",
]
