#!/usr/bin/env python3
"""
feed_all.py — Write all event types into a single merged Kafka topic (events.all).

Each event gets a top-level _type field so StreamForge can discover sub-schemas:
  _type: "payment"        → payment transactions with PII (email)
  _type: "booking"        → flight bookings with PII (passport, DOB, loyalty)
  _type: "iot_sensor"     → IoT sensor readings (6 sensor types, mixed schema)
  _type: "wikipedia_edit" → synthetic Wikipedia-style edit events (no network needed)

Usage:
  # Seed 500 events then run in live mode (default for setup.sh):
  python3 demo/feed_all.py --preseed 500

  # Seed only, then exit (for CI / one-shot seeding):
  python3 demo/feed_all.py --preseed 500 --no-live

  # Live mode only (no preseed):
  python3 demo/feed_all.py

Notes:
  - Payments are ALWAYS phase-1 (clean schema). Drift is injected separately
    via inject_drift.py for predictable demo timing.
  - Wikipedia uses a fully synthetic generator — no external SSE connection.
  - All events go to topic: events.all
"""

import argparse
import json
import logging
import random
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("feed_all")

# ── File logging (activated by STREAMFORGE_LOG_DIR env var) ───────────────────
import os as _os
import pathlib as _pathlib

_LOG_DIR = _os.environ.get("STREAMFORGE_LOG_DIR")
if _LOG_DIR:
    _pathlib.Path(_LOG_DIR).mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(f"{_LOG_DIR}/producer.log")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _root = logging.getLogger()
    # Remove existing StreamHandlers to prevent duplication when stderr is redirected to the log file
    for _h in list(_root.handlers):
        if isinstance(_h, logging.StreamHandler) and not isinstance(_h, logging.FileHandler):
            _root.removeHandler(_h)
    _root.addHandler(_fh)

# ── Per-type event counters (used by metrics thread) ─────────────────────────
_counts: dict = {"payment": 0, "booking": 0, "iot_sensor": 0, "wikipedia_edit": 0}
_counts_lock = threading.Lock()

TOPIC = "events.all"

# ── Kafka producer ─────────────────────────────────────────────────────────────

def make_producer(brokers: str) -> KafkaProducer:
    for attempt in range(15):
        try:
            p = KafkaProducer(
                bootstrap_servers=brokers,
                value_serializer=lambda v: json.dumps(v).encode(),
                linger_ms=20,
                batch_size=16384,
            )
            log.info("Connected to Kafka at %s", brokers)
            return p
        except NoBrokersAvailable:
            log.warning("Kafka not ready, retrying in 3s… (attempt %d/15)", attempt + 1)
            time.sleep(3)
    log.error("Could not connect to Kafka at %s after 45s", brokers)
    sys.exit(1)


def publish(producer: KafkaProducer, event: dict) -> None:
    producer.send(TOPIC, event, key=event.get("_type", "unknown").encode())
    etype = event.get("_type", "unknown")
    if etype in _counts:
        with _counts_lock:
            _counts[etype] += 1


# ── Payment events (always phase-1 / clean schema) ───────────────────────────
# Drift is injected deterministically via inject_drift.py — not via timer here.

_CURRENCIES = ["USD", "EUR", "GBP", "SGD", "AUD", "JPY"]
_STATUSES   = ["pending", "completed", "failed", "refunded"]
_MERCHANTS  = ["stripe", "adyen", "checkout", "braintree", "square"]


def _payment_event() -> dict:
    return {
        "_type": "payment",
        "event_id": str(uuid.uuid4()),
        "event_type": random.choice(["payment.created", "payment.updated", "payment.failed"]),
        "user_id": f"u_{random.randint(1000, 9999)}",
        "merchant": random.choice(_MERCHANTS),
        "currency": random.choice(_CURRENCIES),
        "status": random.choice(_STATUSES),          # always string in clean phase
        "amount": round(random.uniform(1.0, 999.99), 2),  # always float in clean phase
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),  # always epoch ms
        "user_email": f"user{random.randint(100, 999)}@example.com" if random.random() < 0.6 else None,
    }


def feed_payments(producer: KafkaProducer, rate_hz: float = 2.0) -> None:
    log.info("[payment] starting at %.1f events/s", rate_hz)
    interval = 1.0 / rate_hz
    while True:
        publish(producer, _payment_event())
        time.sleep(interval + random.uniform(-0.05, 0.05))


# ── Booking events with PII ───────────────────────────────────────────────────

_AIRLINES = ["BA", "UA", "DL", "LH", "SQ", "EK", "QF", "AF"]
_AIRPORTS = ["LHR", "JFK", "SIN", "DXB", "SYD", "CDG", "NRT", "LAX", "ORD", "FRA"]
_CABINS   = ["economy", "premium_economy", "business", "first"]
_BOOKING_STATUSES = ["confirmed", "pending", "cancelled", "checked_in"]


def _booking_event() -> dict:
    origin, dest = random.sample(_AIRPORTS, 2)
    ev: dict = {
        "_type": "booking",
        "booking_ref": f"BK{random.randint(100000, 999999)}",
        "event_type": random.choice(["booking.created", "booking.updated", "booking.cancelled"]),
        "airline": random.choice(_AIRLINES),
        "origin": origin,
        "destination": dest,
        "cabin": random.choice(_CABINS),
        "status": random.choice(_BOOKING_STATUSES),
        "total_price": round(random.uniform(80.0, 4500.0), 2),
        "currency": random.choice(_CURRENCIES),
        "created_at": datetime.now(UTC).isoformat(),
    }

    # PII: passengers with passport, DOB, loyalty number
    n_passengers = random.randint(1, 3)
    passengers = []
    for _ in range(n_passengers):
        p: dict = {
            "passenger_name": random.choice([
                "Alice Johnson", "Bob Smith", "Carol White", "David Brown",
                "Emma Davis", "Frank Miller", "Grace Wilson", "Henry Moore",
            ]),
            "ticket_number": f"TK{random.randint(1000000, 9999999)}",
        }
        if random.random() < 0.7:
            p["passport_number"] = (
                f"{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(1000000, 9999999)}"
            )
        if random.random() < 0.5:
            p["date_of_birth"] = (
                f"{random.randint(1960, 2000)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
            )
        if random.random() < 0.6:
            p["frequent_flyer_number"] = f"FF{random.randint(100000, 999999)}"
        passengers.append(p)
    ev["passengers"] = passengers

    if random.random() < 0.5:
        ev["contact_email"] = f"traveller{random.randint(100, 999)}@example.com"
    if random.random() < 0.4:
        ev["contact_phone"] = f"+1{random.randint(2000000000, 9999999999)}"
    if random.random() < 0.3:
        ev["baggage_allowance_kg"] = random.choice([20, 23, 25, 30, 32])

    return ev


def feed_bookings(producer: KafkaProducer, rate_hz: float = 1.0) -> None:
    log.info("[booking] starting at %.1f events/s", rate_hz)
    interval = 1.0 / rate_hz
    while True:
        publish(producer, _booking_event())
        time.sleep(interval + random.uniform(-0.1, 0.2))


# ── IoT sensor events ─────────────────────────────────────────────────────────

_SENSOR_TYPES     = ["temperature", "humidity", "pressure", "motion", "power_meter", "air_quality"]
_FIRMWARE         = ["v1.2.0", "v1.2.1", "v1.3.0-beta", "v2.0.0"]
_LOCATIONS        = ["warehouse_a", "warehouse_b", "office_floor_1", "office_floor_2",
                     "server_room", "loading_dock", "rooftop", "basement"]


def _iot_event() -> dict:
    sensor_type = random.choice(_SENSOR_TYPES)
    firmware = random.choice(_FIRMWARE)
    ev: dict = {
        "_type": "iot_sensor",
        "event_type": "iot_sensor",
        "device_id": f"sensor_{random.randint(1, 50):03d}",
        "sensor_type": sensor_type,
        "location": random.choice(_LOCATIONS),
        "firmware": firmware,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if sensor_type == "temperature":
        # Fix: removed legacy v2.0.0 string format ("25.3°C").
        # The string variant caused the schema to infer 'mixed' type, which then
        # triggered false-positive drift on every watch poll (Tier 3 before any
        # inject_drift.py call). Always emit float so the inferred schema matches
        # the live feed consistently.
        ev["temperature_c"] = round(random.uniform(18.0, 35.0), 2)
        ev["battery_pct"] = random.randint(0, 100)
    elif sensor_type == "humidity":
        ev["humidity_pct"] = round(random.uniform(30.0, 85.0), 1)
        ev["dew_point_c"] = round(random.uniform(5.0, 20.0), 2) if random.random() > 0.3 else None
        ev["battery_pct"] = random.randint(0, 100)
    elif sensor_type == "pressure":
        ev["pressure_hpa"] = round(random.uniform(980.0, 1040.0), 2)
        ev["altitude_m"] = round(random.uniform(0, 500), 1) if random.random() > 0.4 else None
    elif sensor_type == "motion":
        ev["motion_detected"] = random.random() < 0.2
        ev["confidence"] = round(random.uniform(0.5, 1.0), 3) if ev["motion_detected"] else None
        ev["zone"] = random.choice(["entry", "corridor", "parking", None])
    elif sensor_type == "power_meter":
        ev["watts"] = round(random.uniform(0, 5000), 1)
        ev["voltage"] = round(random.uniform(220, 240), 1)
        ev["current_amps"] = round(random.uniform(0, 25), 2)
        ev["power_factor"] = round(random.uniform(0.7, 1.0), 3)
        if firmware in ("v1.3.0-beta", "v2.0.0"):
            ev["kwh_today"] = round(random.uniform(0, 50), 3) if random.random() > 0.2 else None
    elif sensor_type == "air_quality":
        ev["co2_ppm"] = random.randint(400, 2000)
        ev["pm25"] = round(random.uniform(0, 50), 1)
        ev["pm10"] = round(random.uniform(0, 100), 1)
        ev["tvoc_ppb"] = random.randint(0, 500) if random.random() > 0.25 else None
        ev["aqi"] = random.randint(0, 300)

    if firmware == "v1.3.0-beta":
        # Fix: removed random.random() < 0.4 gate.
        # Stochastic inclusion (40%) meant the debug block's presence_rate
        # varied between the seed sample and each live watch window, causing
        # false-positive Tier 1 drift ("field_added: debug.rssi") on every poll.
        # Always-include makes the presence_rate deterministic across windows.
        ev["debug"] = {
            "rssi": random.randint(-90, -40),
            "uptime_s": random.randint(0, 86400),
            "free_heap": random.randint(20000, 100000),
        }

    return ev


def feed_iot(producer: KafkaProducer, rate_hz: float = 5.0) -> None:
    log.info("[iot_sensor] starting at %.1f events/s", rate_hz)
    interval = 1.0 / rate_hz
    while True:
        publish(producer, _iot_event())
        time.sleep(interval + random.uniform(-0.02, 0.02))


# ── Synthetic Wikipedia edit events (no external SSE needed) ──────────────────

_WIKI_NAMESPACES = [0, 0, 0, 0, 1, 4, 10, 14]  # 0=article (most common)
_WIKI_TITLES = [
    "Python (programming language)", "Artificial intelligence", "Kafka (software)",
    "Data engineering", "Apache Kafka", "Event-driven architecture", "Schema registry",
    "Machine learning", "Stream processing", "Database normalization",
    "Distributed computing", "Microservices", "DevOps", "Cloud computing",
    "PostgreSQL", "Data lake", "ETL", "Real-time analytics", "Flink", "Spark",
]
_WIKI_USERS = [
    "WikiEditor42", "DataNerd", "TechWriter", "AnonymousContrib", "RobotCleanup",
    "FactChecker", "StyleBot", "LinksFixed", "CitationNeeded", "GrammarPolice",
]


def _wikipedia_event() -> dict:
    title = random.choice(_WIKI_TITLES)
    old_len = random.randint(1000, 50000)
    new_len = old_len + random.randint(-500, 2000)
    return {
        "_type": "wikipedia_edit",
        "event_type": "wikipedia_edit",  # enables routing in StreamForge multi-schema mode
        "wiki": "enwiki",
        "type": random.choice(["edit", "new", "edit", "edit"]),  # mostly edits
        "namespace": random.choice(_WIKI_NAMESPACES),
        "title": title,
        "title_url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
        "comment": random.choice([
            "fixed typo", "added citation", "reverted vandalism",
            "updated statistics", "copyedit", "added section", "removed spam",
        ]),
        "user": random.choice(_WIKI_USERS),
        "bot": random.random() < 0.15,
        "minor": random.random() < 0.4,
        "old_length": old_len,
        "new_length": max(0, new_len),
        "length_delta": new_len - old_len,
        "revision_id": random.randint(1_000_000, 2_000_000_000),
        "parent_revision_id": random.randint(1_000_000, 2_000_000_000),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def feed_wikipedia(producer: KafkaProducer, rate_hz: float = 1.5) -> None:
    log.info("[wikipedia_edit] starting at %.1f events/s (synthetic)", rate_hz)
    interval = 1.0 / rate_hz
    while True:
        publish(producer, _wikipedia_event())
        time.sleep(interval + random.uniform(-0.1, 0.3))


# ── Preseed: burst-write N events across all types then return ────────────────

def preseed(producer: KafkaProducer, n: int) -> None:
    """Write n events as fast as possible (no sleep). ~125 per event type."""
    log.info("Preseeding %d events into %s...", n, TOPIC)
    generators = [_payment_event, _booking_event, _iot_event, _wikipedia_event]
    per_type = n // len(generators)
    total = 0

    for gen in generators:
        for _ in range(per_type):
            publish(producer, gen())
            total += 1

    # Top up to exactly n if not divisible
    while total < n:
        publish(producer, _payment_event())
        total += 1

    producer.flush(timeout=10)
    log.info("Preseed complete: %d events written to %s", total, TOPIC)


# ── Metrics thread ────────────────────────────────────────────────────────────

def _metrics_loop() -> None:
    """Append a throughput snapshot to logs/metrics.log every 30 seconds."""
    if not _LOG_DIR:
        return
    metrics_path = f"{_LOG_DIR}/metrics.log"
    while True:
        time.sleep(30)
        with _counts_lock:
            snapshot = dict(_counts)
        total = sum(snapshot.values())
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        line = (
            f"{ts}  published_total={total}"
            f"  payment={snapshot['payment']}"
            f"  booking={snapshot['booking']}"
            f"  iot_sensor={snapshot['iot_sensor']}"
            f"  wikipedia_edit={snapshot['wikipedia_edit']}\n"
        )
        try:
            with open(metrics_path, "a") as mf:
                mf.write(line)
        except OSError as exc:
            log.warning("Could not write metrics: %s", exc)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Feed all event types into events.all")
    parser.add_argument("--brokers", default="localhost:9092")
    parser.add_argument("--preseed", type=int, default=0,
                        help="Burst-write this many events before going live (0 = skip)")
    parser.add_argument("--no-live", action="store_true",
                        help="Exit after preseed instead of running live feeds")
    parser.add_argument("--payment-rate", type=float, default=2.0, metavar="HZ")
    parser.add_argument("--booking-rate", type=float, default=1.0, metavar="HZ")
    parser.add_argument("--iot-rate",     type=float, default=5.0, metavar="HZ")
    parser.add_argument("--wiki-rate",    type=float, default=1.5, metavar="HZ")
    args = parser.parse_args()

    producer = make_producer(args.brokers)

    if args.preseed > 0:
        preseed(producer, args.preseed)

    if args.no_live:
        producer.flush(timeout=5)
        producer.close()
        print(f"✓ Preseeded {args.preseed} events. Exiting.")
        return

    print(f"\n{'─'*60}")
    print(f"  StreamForge Demo — live feeds → {TOPIC}")
    print(f"{'─'*60}")
    print(f"  payment       → {args.payment_rate:.1f} events/s  (clean schema)")
    print(f"  booking       → {args.booking_rate:.1f} events/s  (PII: passport, DOB, loyalty)")
    print(f"  iot_sensor    → {args.iot_rate:.1f} events/s  (6 sensor types, mixed schema)")
    print(f"  wikipedia_edit→ {args.wiki_rate:.1f} events/s  (synthetic)")
    print(f"{'─'*60}")
    print("  Drift injected on demand via: python3 demo/inject_drift.py")
    print("  Kafka UI: http://localhost:8080")
    print("  Stop with Ctrl+C")
    print(f"{'─'*60}\n")

    threads = [
        threading.Thread(target=feed_payments,  args=(producer, args.payment_rate), daemon=True, name="payment"),
        threading.Thread(target=feed_bookings,  args=(producer, args.booking_rate), daemon=True, name="booking"),
        threading.Thread(target=feed_iot,       args=(producer, args.iot_rate),     daemon=True, name="iot"),
        threading.Thread(target=feed_wikipedia, args=(producer, args.wiki_rate),    daemon=True, name="wiki"),
        threading.Thread(target=_metrics_loop, daemon=True, name="metrics"),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping feeds…")
        producer.flush(timeout=5)
        producer.close()


if __name__ == "__main__":
    main()
