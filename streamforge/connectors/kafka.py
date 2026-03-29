"""
streamforge/connectors/kafka.py — Kafka Stream Connector
=========================================================

Implements the StreamConnector interface (connectors/base.py) for Apache Kafka
and any Kafka-protocol-compatible broker:
  - Apache Kafka (self-hosted, AWS MSK, Confluent Cloud)
  - Redpanda (drop-in Kafka replacement)
  - Azure Event Hubs (Kafka protocol mode)

Design decisions:
  ADR-008: kafka-python as the default library (pure Python, zero native deps,
           installs anywhere). confluent-kafka-python is faster for production
           but requires librdkafka to be present. We try confluent-kafka first
           and fall back to kafka-python transparently.

  ADR-009: At-least-once semantics. We commit offsets AFTER processing a batch,
           never before. If StreamForge crashes mid-batch, it re-reads from the
           last committed offset on restart. This is the right tradeoff for a
           schema profiler — a duplicate read is fine, a missed event is not.

  ADR-010: KafkaConnector is a context manager (async with KafkaConnector(...)).
           This ensures the consumer is always closed, releasing group membership
           and allowing other consumers in the group to rebalance quickly.

  ADR-011: We deliberately read from the BEGINNING of the topic by default
           (auto_offset_reset = "earliest") because the goal of 'init' is to
           build a representative schema. Tail-only reading would miss historical
           event shapes. The consumer group name (default: "streamforge-profiler")
           is designed to be unique so we don't interfere with production groups.

Usage:
    from streamforge.connectors.kafka import KafkaConnector
    from streamforge.config import Config

    cfg = Config()
    cfg.kafka.bootstrap_servers = ["localhost:9092"]

    async with KafkaConnector("my-topic", cfg.kafka) as conn:
        while True:
            batch = await conn.read_batch(max_messages=500)
            if not batch:
                break
            process(batch)
            await conn.ack()
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..config import KafkaConfig
from .base import StreamConnector

logger = logging.getLogger(__name__)


# ── Library detection ──────────────────────────────────────────────────────────
# Try confluent-kafka first (faster, better for production).
# Fall back to kafka-python (pure Python, zero native deps, easier to install).

_CONFLUENT_AVAILABLE = False
_KAFKA_PYTHON_AVAILABLE = False

try:
    from confluent_kafka import Consumer as ConfluentConsumer
    from confluent_kafka import KafkaError
    _CONFLUENT_AVAILABLE = True
    logger.debug("Using confluent-kafka (C-based, production grade)")
except ImportError:
    pass

if not _CONFLUENT_AVAILABLE:
    try:
        from kafka import KafkaConsumer  # type: ignore[import]
        from kafka.errors import KafkaError  # type: ignore[import]
        _KAFKA_PYTHON_AVAILABLE = True
        logger.debug("Using kafka-python (pure Python)")
    except ImportError:
        pass


class KafkaConnectorError(RuntimeError):
    """Raised when neither kafka library is available or connection fails."""


class KafkaConnector(StreamConnector):
    """
    Kafka consumer implementing the StreamConnector interface.

    Supports PLAINTEXT, SSL, SASL_SSL (PLAIN, SCRAM-SHA-256, SCRAM-SHA-512).
    Reads one topic at a time. Does not support consumer group rebalancing
    (intentional — StreamForge reads for profiling, not for continuous ETL).

    Attributes:
        topic:         Kafka topic name to consume.
        cfg:           KafkaConfig with all connection parameters.
        _consumer:     Underlying consumer instance (confluent or kafka-python).
        _last_batch:   Most recently read batch (used by ack() for offset commit).
    """

    def __init__(self, topic: str, cfg: KafkaConfig) -> None:
        if not _CONFLUENT_AVAILABLE and not _KAFKA_PYTHON_AVAILABLE:
            raise KafkaConnectorError(
                "No Kafka client library found. Install one of:\n"
                "  pip install kafka-python          # pure Python, easier\n"
                "  pip install confluent-kafka        # C-based, faster (requires librdkafka)\n"
            )
        self.topic = topic
        self.cfg = cfg
        self._consumer: Any = None
        self._last_batch: list[dict] = []
        self._messages_read: int = 0
        self._start_time: float = time.monotonic()

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> KafkaConnector:
        """Create and configure the Kafka consumer."""
        logger.info(
            "Connecting to Kafka",
            extra={
                "topic": self.topic,
                "brokers": self.cfg.bootstrap_servers,
                "security": self.cfg.security_protocol,
                "group": self.cfg.consumer_group,
                "offset_reset": self.cfg.auto_offset_reset,
            },
        )
        if _CONFLUENT_AVAILABLE:
            self._consumer = self._build_confluent_consumer()
        else:
            consumer = self._build_kafka_python_consumer()
            # Explicitly assign ALL partitions of the topic so that the
            # first poll() reads from every partition, not just whichever
            # fills its fetch buffer first.  subscribe() is asynchronous
            # and leads to skewed sampling from whichever partition
            # completes rebalance fastest.
            try:
                partitions = consumer.partitions_for_topic(self.topic) or set()
                if partitions:
                    from kafka import TopicPartition as _TP
                    tps = [_TP(self.topic, p) for p in sorted(partitions)]
                    consumer.assign(tps)
                    # For earliest-reset consumers (init / plan) we must seek
                    # explicitly; committed offsets from prior runs are ignored
                    # because assign() bypasses the group coordinator.
                    if self.cfg.auto_offset_reset == "earliest":
                        consumer.seek_to_beginning(*tps)
                    logger.debug(
                        "Assigned %d partition(s) explicitly", len(tps),
                        extra={"topic": self.topic, "partitions": sorted(partitions)},
                    )
            except Exception as exc:
                logger.warning("Could not assign partitions explicitly: %s — falling back to subscribe()", exc)
                consumer.subscribe([self.topic])
            self._consumer = consumer

        self._start_time = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Close the consumer, releasing group membership."""
        if self._consumer is not None:
            try:
                if _CONFLUENT_AVAILABLE:
                    self._consumer.close()
                else:
                    self._consumer.close()
                logger.info(
                    "Kafka consumer closed",
                    extra={"topic": self.topic, "total_messages": self._messages_read},
                )
            except Exception as e:
                logger.warning("Error closing Kafka consumer: %s", e)
        # Don't suppress exceptions
        return False

    # ── Public interface (StreamConnector protocol) ───────────────────────────

    async def read_batch(
        self,
        max_messages: int = 500,
        timeout_ms: int = 5_000,
    ) -> list[dict]:
        """
        Poll for up to max_messages from the topic.

        Returns:
            List of parsed event dicts. Empty list if no messages arrived
            within timeout_ms.

        Note:
            Messages that cannot be parsed as JSON are logged and skipped.
            We never block on them — partial data is better than no data.
        """
        if _CONFLUENT_AVAILABLE:
            return self._read_confluent(max_messages, timeout_ms)
        else:
            return self._read_kafka_python(max_messages, timeout_ms)

    async def ack(self) -> None:
        """
        Commit offsets for the last batch (at-least-once semantics).
        Call this AFTER successfully processing read_batch() output.
        """
        if not self._last_batch:
            return
        try:
            if _CONFLUENT_AVAILABLE:
                self._consumer.commit(asynchronous=False)
            else:
                self._consumer.commit()
            logger.debug("Committed offsets", extra={"batch_size": len(self._last_batch)})
        except Exception as e:
            logger.warning("Failed to commit offsets: %s", e)

    async def close(self) -> None:
        """Explicit close (also called by __aexit__)."""
        await self.__aexit__(None, None, None)

    @property
    def source_id(self) -> str:
        """Human-readable identifier for logging and UI."""
        brokers = ",".join(self.cfg.bootstrap_servers[:2])
        if len(self.cfg.bootstrap_servers) > 2:
            brokers += f",+{len(self.cfg.bootstrap_servers) - 2}"
        return f"kafka://{brokers}/{self.topic}"

    # ── Synchronous helpers (called from async wrappers above) ───────────────

    def _read_confluent(self, max_messages: int, timeout_ms: int) -> list[dict]:
        """Poll using confluent-kafka consumer."""
        events: list[dict] = []
        timeout_s = timeout_ms / 1_000
        deadline = time.monotonic() + timeout_s

        while len(events) < max_messages and time.monotonic() < deadline:
            # Poll returns one message at a time in confluent-kafka
            remaining = max(0.1, deadline - time.monotonic())
            msg = self._consumer.poll(timeout=remaining)

            if msg is None:
                break  # Timeout with no message

            if msg.error():
                err = msg.error()
                if err.code() == KafkaError._PARTITION_EOF:
                    # End of one partition — other partitions may still have data
                    logger.debug("Reached end of partition %s", msg.partition())
                    continue
                logger.error("Kafka error: %s", err)
                break

            parsed = self._parse_message(msg.value())
            if parsed is not None:
                events.append(parsed)

        self._last_batch = events
        self._messages_read += len(events)

        if events:
            elapsed = time.monotonic() - self._start_time
            logger.debug(
                "Batch read complete",
                extra={"count": len(events), "total": self._messages_read, "elapsed_s": round(elapsed, 2)},
            )

        return events

    def _read_kafka_python(self, max_messages: int, timeout_ms: int) -> list[dict]:
        """Poll using kafka-python consumer.

        For earliest-offset consumers (init / plan): reads one partition at a
        time and distributes the budget evenly.  kafka-python's poll() fills
        max_records from whichever partition's fetch buffer is ready first;
        reading per-partition prevents one partition from starving others.

        For latest-offset consumers (watch / ping): uses a simple poll loop.
        Events are actively being produced, so all partitions will have
        pending records and poll() naturally interleaves them.
        """
        events: list[dict] = []
        deadline = time.monotonic() + timeout_ms / 1_000

        if self.cfg.auto_offset_reset != "earliest":
            # ── Latest mode: simple loop ──────────────────────────────────
            while len(events) < max_messages and time.monotonic() < deadline:
                remaining_ms = max(100, int((deadline - time.monotonic()) * 1_000))
                raw = self._consumer.poll(
                    timeout_ms=remaining_ms,
                    max_records=max_messages - len(events),
                )
                if not raw:
                    break
                for msgs in raw.values():
                    for m in msgs:
                        if len(events) >= max_messages:
                            break
                        parsed = self._parse_message(m.value)
                        if parsed is not None:
                            events.append(parsed)
            self._last_batch = events
            self._messages_read += len(events)
            return events

        # ── Earliest mode: per-partition reading ─────────────────────────
        # kafka-python's poll() fills max_records from whichever single
        # partition fills its fetch buffer first, silently skipping others.
        # Reading one partition at a time guarantees all partitions
        # contribute to the sample.
        assigned = list(self._consumer.assignment())
        if not assigned:
            raw = self._consumer.poll(timeout_ms=timeout_ms, max_records=max_messages)
            for msgs in raw.values():
                for m in msgs:
                    if len(events) >= max_messages:
                        break
                    parsed = self._parse_message(m.value)
                    if parsed is not None:
                        events.append(parsed)
            self._last_batch = events
            self._messages_read += len(events)
            return events

        per_partition = max(1, max_messages // len(assigned))
        ms_per_partition = max(500, int(timeout_ms / len(assigned)))

        for tp in sorted(assigned, key=lambda p: p.partition):
            if len(events) >= max_messages or time.monotonic() >= deadline:
                break

            want = min(per_partition, max_messages - len(events))
            tp_deadline = min(deadline, time.monotonic() + ms_per_partition / 1_000)

            self._consumer.assign([tp])
            tp_events: list[dict] = []

            while len(tp_events) < want and time.monotonic() < tp_deadline:
                remaining_ms = max(100, int((tp_deadline - time.monotonic()) * 1_000))
                raw = self._consumer.poll(
                    timeout_ms=remaining_ms,
                    max_records=want - len(tp_events),
                )
                if not raw:
                    break
                for msgs in raw.values():
                    for m in msgs:
                        if len(tp_events) >= want:
                            break
                        parsed = self._parse_message(m.value)
                        if parsed is not None:
                            tp_events.append(parsed)

            events.extend(tp_events)

        self._consumer.assign(assigned)
        self._last_batch = events
        self._messages_read += len(events)
        return events

    def _parse_message(self, raw: bytes | None) -> dict | None:
        """
        Parse a raw Kafka message value into a dict.

        Handles:
          - JSON byte strings (most common)
          - JSON with leading/trailing whitespace
          - Messages that are None or empty (tombstones in log-compacted topics)
          - Invalid JSON — logged and skipped, never raised
        """
        if not raw:
            return None  # Tombstone or empty message — skip silently
        try:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                return None
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.debug("Skipping non-JSON message: %s (first 80 chars: %r)", e, raw[:80])
            return None
        except Exception as e:
            logger.warning("Unexpected error parsing message: %s", e)
            return None

    # ── Consumer factory methods ───────────────────────────────────────────────

    def _build_confluent_consumer(self) -> Any:
        """Build a confluent-kafka Consumer with the configured settings."""
        conf = {
            "bootstrap.servers":   ",".join(self.cfg.bootstrap_servers),
            "group.id":            self.cfg.consumer_group,
            "auto.offset.reset":   self.cfg.auto_offset_reset,
            "enable.auto.commit":  False,        # We commit manually after ack()
            "security.protocol":   self.cfg.security_protocol,
            "max.poll.interval.ms": 300_000,     # 5 min — profiling can be slow
            "session.timeout.ms":  self.cfg.session_timeout_ms,
        }

        # SASL authentication
        if self.cfg.sasl_mechanism:
            conf["sasl.mechanism"] = self.cfg.sasl_mechanism
        if self.cfg.sasl_username:
            conf["sasl.username"] = self.cfg.sasl_username
        if self.cfg.sasl_password:
            conf["sasl.password"] = self.cfg.sasl_password

        # SSL / mTLS
        if self.cfg.ssl_ca_location:
            conf["ssl.ca.location"] = self.cfg.ssl_ca_location
        if self.cfg.ssl_cert_location:
            conf["ssl.certificate.location"] = self.cfg.ssl_cert_location
        if self.cfg.ssl_key_location:
            conf["ssl.key.location"] = self.cfg.ssl_key_location

        consumer = ConfluentConsumer(conf)
        consumer.subscribe([self.topic])
        return consumer

    def _build_kafka_python_consumer(self) -> Any:
        """Build a kafka-python KafkaConsumer with the configured settings."""
        kwargs: dict[str, Any] = {
            "bootstrap_servers":    self.cfg.bootstrap_servers,
            "group_id":             self.cfg.consumer_group,
            "auto_offset_reset":    self.cfg.auto_offset_reset,
            "enable_auto_commit":   False,       # Manual commit via ack()
            "max_poll_records":     self.cfg.max_poll_records,
            "session_timeout_ms":   self.cfg.session_timeout_ms,
            # kafka-python requires request_timeout_ms > session_timeout_ms
            "request_timeout_ms":   max(self.cfg.request_timeout_ms, self.cfg.session_timeout_ms + 10_000),
            "value_deserializer":   None,        # We handle deserialization ourselves
            "security_protocol":    self.cfg.security_protocol,
        }

        # SASL
        if self.cfg.sasl_mechanism:
            kwargs["sasl_mechanism"] = self.cfg.sasl_mechanism
        if self.cfg.sasl_username:
            kwargs["sasl_plain_username"] = self.cfg.sasl_username
        if self.cfg.sasl_password:
            kwargs["sasl_plain_password"] = self.cfg.sasl_password

        # SSL
        if self.cfg.ssl_ca_location:
            kwargs["ssl_cafile"] = self.cfg.ssl_ca_location
        if self.cfg.ssl_cert_location:
            kwargs["ssl_certfile"] = self.cfg.ssl_cert_location
        if self.cfg.ssl_key_location:
            kwargs["ssl_keyfile"] = self.cfg.ssl_key_location

        # Do NOT pass the topic here — we assign partitions explicitly in
        # __aenter__ after calling partitions_for_topic().  This lets us use
        # assign() instead of subscribe() so partition assignment is
        # synchronous and we can call seek_to_beginning() before the first
        # poll().  Without this, poll() may return up to max_records from
        # whichever single partition fills its fetch buffer first, silently
        # skipping the others.
        consumer = KafkaConsumer(**kwargs)
        return consumer


# ── Convenience function for non-async callers (CLI) ──────────────────────────

def sample_from_kafka(
    topic: str,
    cfg: KafkaConfig,
    target: int = 1_000,
    max_wait_seconds: int = 60,
) -> tuple[list[dict], dict]:
    """
    Synchronous helper: collect up to `target` events from a Kafka topic.

    Used by the 'init' CLI command which is synchronous (Typer doesn't run
    an asyncio event loop). We run the async connector in a new event loop.

    Args:
        topic:             Kafka topic name.
        cfg:               KafkaConfig with connection parameters.
        target:            How many events to collect before returning.
        max_wait_seconds:  Give up after this many seconds even if target not met.

    Returns:
        (events, stats) where stats has: total_collected, elapsed_s, source_id.
    """
    import asyncio

    async def _collect() -> tuple[list[dict], dict]:
        events: list[dict] = []
        start = time.monotonic()

        async with KafkaConnector(topic, cfg) as conn:
            while len(events) < target:
                elapsed = time.monotonic() - start
                if elapsed > max_wait_seconds:
                    logger.info("Max wait time reached", extra={"elapsed_s": elapsed, "collected": len(events)})
                    break

                batch = await conn.read_batch(
                    max_messages=min(500, target - len(events)),
                    timeout_ms=5_000,
                )
                if not batch:
                    logger.debug("No more messages — topic drained or timeout")
                    break

                events.extend(batch)
                await conn.ack()

                logger.info(
                    "Sampling progress",
                    extra={"collected": len(events), "target": target, "topic": topic},
                )

        return events, {
            "total_collected": len(events),
            "elapsed_s": round(time.monotonic() - start, 2),
            "source_id": f"kafka://{','.join(cfg.bootstrap_servers[:1])}/{topic}",
        }

    return asyncio.run(_collect())
