"""
streamforge/dlq.py — Dead Letter Queue routing for non-conforming events.

Design principles:
  - NEVER blocks the main processing path
  - NEVER raises — all errors are logged and swallowed
  - Only activated when dlq.enabled=true in topic config
  - Only routes Tier-3 DRIFT events (not evolution, not noise)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DLQConfig:
    enabled: bool = False
    topic_suffix: str = ".dlq"
    include_payload: bool = True
    min_tier: int = 3


class DLQRouter:
    def __init__(self, source_topic: str, brokers: list[str], config: DLQConfig):
        self.dlq_topic = source_topic + config.topic_suffix
        self.brokers = brokers
        self.config = config
        self._producer = None

    def route(self, events: list[dict], violation_type: str, producer_id: str | None = None) -> int:
        """
        Route non-conforming events to DLQ topic.
        Returns count of events successfully routed. Never raises.
        """
        if not self.config.enabled:
            return 0
        try:
            return self._publish(events, violation_type, producer_id)
        except Exception as e:
            logger.warning("DLQ routing failed (non-fatal): %s", e)
            return 0

    def _publish(self, events: list[dict], violation_type: str, producer_id: str | None) -> int:
        # Lazy import kafka-python — only if DLQ is enabled
        try:
            import json

            from kafka import KafkaProducer
        except ImportError:
            logger.warning("kafka-python not installed — DLQ disabled")
            return 0

        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self.brokers,
                value_serializer=lambda v: json.dumps(v).encode(),
            )
        count = 0
        for event in events:
            import time as _time
            payload: dict = {
                "sf_violation_type": violation_type,
                "sf_detected_at": _time.time(),
                "sf_source_topic": self.dlq_topic.removesuffix(self.config.topic_suffix),
                "sf_producer_id": producer_id,
            }
            if self.config.include_payload:
                payload["original_event"] = event
            self._producer.send(self.dlq_topic, payload)
            count += 1
        self._producer.flush(timeout=5)
        return count
