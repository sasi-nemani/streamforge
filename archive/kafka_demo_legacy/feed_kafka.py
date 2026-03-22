#!/usr/bin/env python3
"""
feed_kafka.py — Push free real-world data streams into local Kafka topics.

Sources:
  events.wikipedia  → Wikimedia SSE stream (live edits, creates, deletes — 5+ event types)
  events.github     → GitHub public events API (push, PR, issues, forks — 15+ types)
  events.payments   → Synthetic payments with intentional schema drift over time
  events.bookings   → Synthetic flight bookings with PII variation + optional fields
  events.flights    → OpenSky Network live flight positions (real aircraft ADS-B)
  events.iot        → Synthetic IoT sensors with mixed types and occasional null storms

Usage:
  python feed_kafka.py                          # all sources
  python feed_kafka.py --topics wikipedia,github
  python feed_kafka.py --brokers localhost:9092

Stop with Ctrl+C.
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

import httpx
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("feed")

# ── Kafka producer ─────────────────────────────────────────────────────────────

def make_producer(brokers: str) -> KafkaProducer:
    for attempt in range(10):
        try:
            p = KafkaProducer(
                bootstrap_servers=brokers,
                value_serializer=lambda v: json.dumps(v).encode(),
                linger_ms=50,
                batch_size=16384,
            )
            log.info("Connected to Kafka at %s", brokers)
            return p
        except NoBrokersAvailable:
            log.warning("Kafka not ready, retrying in 3s… (attempt %d/10)", attempt + 1)
            time.sleep(3)
    log.error("Could not connect to Kafka at %s", brokers)
    sys.exit(1)


def publish(producer: KafkaProducer, topic: str, event: dict) -> None:
    producer.send(topic, event)


# ── Wikipedia live edits (SSE) ─────────────────────────────────────────────────
# Real endpoint: https://stream.wikimedia.org/v2/stream/recentchange
# Emits ~10-30 events/second. Lots of schema variety (edit, new, log, categorize).

def feed_wikipedia(producer: KafkaProducer, topic: str) -> None:
    """Stream Wikimedia recent-changes SSE → Kafka."""
    log.info("[wikipedia] starting SSE stream")
    url = "https://stream.wikimedia.org/v2/stream/recentchange"
    headers = {"User-Agent": "StreamForge-Demo/1.0 (schema drift demo; https://github.com/streamforge)"}
    while True:
        try:
            with httpx.Client(timeout=None, headers=headers) as client:
                with client.stream("GET", url) as resp:
                    buffer = ""
                    for line in resp.iter_lines():
                        if line.startswith("data:"):
                            buffer = line[5:].strip()
                        elif line == "" and buffer:
                            try:
                                event = json.loads(buffer)
                                # Keep interesting fields, drop internal SSE metadata
                                event.pop("$schema", None)
                                event["_ingested_at"] = datetime.now(UTC).isoformat()
                                publish(producer, topic, event)
                                log.debug("[wikipedia] %s %s", event.get("type"), event.get("title", "")[:40])
                            except json.JSONDecodeError:
                                pass
                            buffer = ""
        except Exception as e:
            log.warning("[wikipedia] stream error: %s — reconnecting in 5s", e)
            time.sleep(5)


# ── GitHub public events (REST polling) ───────────────────────────────────────
# Free, no auth needed (60 req/hr unauthenticated). Returns 30 recent events.
# ~15 event types: PushEvent, PullRequestEvent, IssuesEvent, ForkEvent, etc.
# Schema varies heavily by type — great for multi-schema demo.

def feed_github(producer: KafkaProducer, topic: str) -> None:
    """Poll GitHub public events API → Kafka (dedup by event id)."""
    log.info("[github] starting poll loop")
    seen: set[str] = set()
    url = "https://api.github.com/events"
    while True:
        try:
            resp = httpx.get(url, headers={"Accept": "application/vnd.github+json"}, timeout=15)
            if resp.status_code == 200:
                events = resp.json()
                new_count = 0
                for ev in events:
                    eid = ev.get("id", "")
                    if eid in seen:
                        continue
                    seen.add(eid)
                    # Flatten slightly — keep type, actor, repo, created_at, payload summary
                    flat = {
                        "id": eid,
                        "type": ev.get("type"),
                        "actor_login": ev.get("actor", {}).get("login"),
                        "actor_id": ev.get("actor", {}).get("id"),
                        "repo_name": ev.get("repo", {}).get("name"),
                        "created_at": ev.get("created_at"),
                        "_ingested_at": datetime.now(UTC).isoformat(),
                    }
                    # Include type-specific payload fields (creates schema variety)
                    payload = ev.get("payload", {})
                    if ev.get("type") == "PushEvent":
                        flat["push_ref"] = payload.get("ref")
                        flat["push_size"] = payload.get("size")
                        flat["push_distinct_size"] = payload.get("distinct_size")
                        commits = payload.get("commits", [])
                        flat["commit_message"] = commits[0].get("message", "")[:120] if commits else None
                    elif ev.get("type") == "PullRequestEvent":
                        pr = payload.get("pull_request", {})
                        flat["pr_action"] = payload.get("action")
                        flat["pr_title"] = pr.get("title", "")[:100]
                        flat["pr_state"] = pr.get("state")
                        flat["pr_merged"] = pr.get("merged")
                        flat["pr_additions"] = pr.get("additions")
                        flat["pr_deletions"] = pr.get("deletions")
                    elif ev.get("type") == "IssuesEvent":
                        issue = payload.get("issue", {})
                        flat["issue_action"] = payload.get("action")
                        flat["issue_title"] = issue.get("title", "")[:100]
                        flat["issue_state"] = issue.get("state")
                        flat["issue_labels"] = [l.get("name") for l in issue.get("labels", [])]
                    elif ev.get("type") == "WatchEvent":
                        flat["watch_action"] = payload.get("action")
                    elif ev.get("type") == "ForkEvent":
                        forkee = payload.get("forkee", {})
                        flat["fork_full_name"] = forkee.get("full_name")
                        flat["fork_private"] = forkee.get("private")
                    elif ev.get("type") == "CreateEvent":
                        flat["create_ref_type"] = payload.get("ref_type")
                        flat["create_ref"] = payload.get("ref")
                        flat["create_description"] = (payload.get("description") or "")[:80]
                    publish(producer, topic, flat)
                    new_count += 1
                if new_count:
                    log.info("[github] published %d new events", new_count)
                # Keep seen set bounded
                if len(seen) > 500:
                    seen = set(list(seen)[-200:])
            elif resp.status_code == 403:
                log.warning("[github] rate-limited, sleeping 60s")
                time.sleep(60)
                continue
        except Exception as e:
            log.warning("[github] error: %s", e)
        time.sleep(30)  # GitHub updates ~every 30s


# ── Synthetic payments with intentional schema drift ─────────────────────────
# Phase 1 (first 5 min): classic schema — amount (float), timestamp (epoch ms)
# Phase 2 (after 5 min): drift injected — amount_minor_units (int), timestamp (ISO),
#                         new required field card_last_four, amount field disappears

_PAYMENT_START = time.time()
_CURRENCIES = ["USD", "EUR", "GBP", "SGD", "AUD", "JPY"]
_STATUSES   = ["pending", "completed", "failed", "refunded"]
_MERCHANTS  = ["stripe", "adyen", "checkout", "braintree", "square"]

def _payment_event() -> dict:
    age = time.time() - _PAYMENT_START
    drift_phase = age > 300  # drift kicks in after 5 minutes

    ev: dict = {
        "event_id": str(uuid.uuid4()),
        "event_type": random.choice(["payment.created", "payment.updated", "payment.failed"]),
        "user_id": f"u_{random.randint(1000, 9999)}",
        "merchant": random.choice(_MERCHANTS),
        "currency": random.choice(_CURRENCIES),
        "status": random.choice(_STATUSES),
        "_ingested_at": datetime.now(UTC).isoformat(),
    }

    if not drift_phase:
        # Phase 1: clean schema
        ev["amount"] = round(random.uniform(1.0, 999.99), 2)
        ev["timestamp"] = int(datetime.now(UTC).timestamp() * 1000)  # epoch ms
        if random.random() < 0.6:
            ev["user_email"] = f"user{random.randint(100,999)}@example.com"
    else:
        # Phase 2: drifted schema
        ev["amount_minor_units"] = random.randint(100, 99999)  # amount gone, new field
        ev["timestamp"] = datetime.now(UTC).isoformat()        # epoch → ISO8601
        ev["card_last_four"] = str(random.randint(1000, 9999)) # new PII field
        if random.random() < 0.3:
            ev["amount"] = None   # occasionally null (presence drop)
        # Occasionally mixed type on status
        if random.random() < 0.1:
            ev["status"] = random.randint(0, 3)  # was string, now integer

    return ev


def feed_payments(producer: KafkaProducer, topic: str, rate_hz: float = 2.0) -> None:
    log.info("[payments] starting (drift kicks in after 5 min)")
    interval = 1.0 / rate_hz
    while True:
        publish(producer, topic, _payment_event())
        time.sleep(interval + random.uniform(-0.1, 0.1))


# ── Synthetic bookings with PII + optional fields ─────────────────────────────
_AIRLINES   = ["BA", "UA", "DL", "LH", "SQ", "EK", "QF", "AF"]
_AIRPORTS   = ["LHR", "JFK", "SIN", "DXB", "SYD", "CDG", "NRT", "LAX", "ORD", "FRA"]
_CABINS     = ["economy", "premium_economy", "business", "first"]
_BOOKING_STATUSES = ["confirmed", "pending", "cancelled", "checked_in"]

def _booking_event() -> dict:
    origin, dest = random.sample(_AIRPORTS, 2)
    ev: dict = {
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
        "_ingested_at": datetime.now(UTC).isoformat(),
    }

    # PII fields — sometimes present, sometimes not (presence variation)
    n_passengers = random.randint(1, 4)
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
            p["passport_number"] = f"{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(1000000, 9999999)}"
        if random.random() < 0.5:
            p["date_of_birth"] = f"{random.randint(1960,2000)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        if random.random() < 0.6:
            p["frequent_flyer_number"] = f"FF{random.randint(100000, 999999)}"
        passengers.append(p)
    ev["passengers"] = passengers

    # Optional fields
    if random.random() < 0.5:
        ev["contact_email"] = f"traveller{random.randint(100,999)}@example.com"
    if random.random() < 0.4:
        ev["contact_phone"] = f"+1{random.randint(2000000000, 9999999999)}"
    if random.random() < 0.3:
        ev["baggage_allowance_kg"] = random.choice([20, 23, 25, 30, 32])
    if random.random() < 0.2:
        ev["seat_preference"] = random.choice(["window", "aisle", "middle", None])
    if random.random() < 0.15:
        ev["special_meal"] = random.choice(["VGML", "KSML", "HNML", "DBML", None])

    return ev


def feed_bookings(producer: KafkaProducer, topic: str, rate_hz: float = 1.0) -> None:
    log.info("[bookings] starting")
    interval = 1.0 / rate_hz
    while True:
        publish(producer, topic, _booking_event())
        time.sleep(interval + random.uniform(-0.1, 0.3))


# ── OpenSky Network live flight positions ─────────────────────────────────────
# Free, no auth, covers commercial flights globally with ADS-B transponder data.
# Schema: varied — some fields null depending on aircraft transponder capability.

def feed_flights(producer: KafkaProducer, topic: str) -> None:
    """Poll OpenSky Network API for live flight state vectors → Kafka."""
    log.info("[flights] starting — polling OpenSky Network")
    url = "https://opensky-network.org/api/states/all"
    # Bounding box: Western Europe (busy airspace)
    params = {"lamin": 35.0, "lomin": -10.0, "lamax": 60.0, "lomax": 30.0}
    fields = [
        "icao24", "callsign", "origin_country", "time_position", "last_contact",
        "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
        "true_track", "vertical_rate", "sensors", "geo_altitude",
        "squawk", "spi", "position_source",
    ]
    while True:
        try:
            resp = httpx.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                states = data.get("states", []) or []
                # Sample up to 50 aircraft per poll to avoid flooding
                sample = random.sample(states, min(50, len(states)))
                for s in sample:
                    ev = dict(zip(fields, s, strict=False))
                    ev["_ingested_at"] = datetime.now(UTC).isoformat()
                    # callsign has trailing spaces in ADS-B
                    if ev.get("callsign"):
                        ev["callsign"] = ev["callsign"].strip()
                    publish(producer, topic, ev)
                log.info("[flights] published %d aircraft positions", len(sample))
            elif resp.status_code == 429:
                log.warning("[flights] rate limited, sleeping 60s")
                time.sleep(60)
                continue
            elif resp.status_code in (401, 403):
                log.warning("[flights] auth required for this endpoint, switching to synthetic fallback")
                _feed_flights_synthetic(producer, topic)
                return
        except Exception as e:
            log.warning("[flights] error: %s", e)
        time.sleep(15)


def _feed_flights_synthetic(producer: KafkaProducer, topic: str) -> None:
    """Fallback: synthetic flight data when OpenSky is unavailable."""
    log.info("[flights] using synthetic fallback")
    airlines = ["BA", "UA", "DL", "LH", "SQ", "EK", "QF", "AF", "AA", "KL"]
    while True:
        flight_num = f"{random.choice(airlines)}{random.randint(100, 9999)}"
        ev = {
            "icao24": f"{random.randint(0, 0xFFFFFF):06x}",
            "callsign": flight_num,
            "origin_country": random.choice(["United Kingdom", "United States", "Germany", "Singapore"]),
            "time_position": int(time.time()),
            "last_contact": int(time.time()),
            "longitude": random.uniform(-10.0, 30.0),
            "latitude": random.uniform(35.0, 60.0),
            "baro_altitude": random.choice([None, random.uniform(1000, 12500)]),
            "on_ground": random.random() < 0.05,
            "velocity": random.choice([None, random.uniform(150, 280)]),
            "true_track": random.uniform(0, 360),
            "vertical_rate": random.choice([None, random.uniform(-15, 15)]),
            "geo_altitude": random.choice([None, random.uniform(1000, 12500)]),
            "squawk": str(random.randint(1000, 7777)) if random.random() < 0.6 else None,
            "spi": False,
            "position_source": random.randint(0, 3),
            "_ingested_at": datetime.now(UTC).isoformat(),
        }
        publish(producer, topic, ev)
        time.sleep(random.uniform(0.3, 0.8))


# ── Synthetic IoT sensors with type variation ─────────────────────────────────
# Mixed sensors: temperature, humidity, pressure, motion, power.
# Intentional messiness: occasional string where float expected, null storms,
# extra debug fields in some firmware versions.

_SENSOR_TYPES = ["temperature", "humidity", "pressure", "motion", "power_meter", "air_quality"]
_FIRMWARE_VERSIONS = ["v1.2.0", "v1.2.1", "v1.3.0-beta", "v2.0.0"]
_LOCATIONS = ["warehouse_a", "warehouse_b", "office_floor_1", "office_floor_2",
              "server_room", "loading_dock", "rooftop", "basement"]

def _iot_event() -> dict:
    sensor_type = random.choice(_SENSOR_TYPES)
    firmware = random.choice(_FIRMWARE_VERSIONS)
    ev: dict = {
        "device_id": f"sensor_{random.randint(1, 50):03d}",
        "sensor_type": sensor_type,
        "location": random.choice(_LOCATIONS),
        "firmware": firmware,
        "timestamp": datetime.now(UTC).isoformat(),
        "_ingested_at": datetime.now(UTC).isoformat(),
    }

    # Type-specific readings
    if sensor_type == "temperature":
        # v2.0.0 sends string with unit, older sends float — classic drift
        if firmware == "v2.0.0":
            ev["temperature_c"] = f"{random.uniform(18.0, 35.0):.1f}°C"  # string!
        else:
            ev["temperature_c"] = round(random.uniform(18.0, 35.0), 2)
        ev["temperature_f"] = round(ev["temperature_c"] * 1.8 + 32, 2) if isinstance(ev["temperature_c"], float) else None
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
        # v1.3.0-beta introduced kwh_today but sometimes sends null
        if firmware in ("v1.3.0-beta", "v2.0.0"):
            ev["kwh_today"] = round(random.uniform(0, 50), 3) if random.random() > 0.2 else None

    elif sensor_type == "air_quality":
        ev["co2_ppm"] = random.randint(400, 2000)
        ev["pm25"] = round(random.uniform(0, 50), 1)
        ev["pm10"] = round(random.uniform(0, 100), 1)
        ev["tvoc_ppb"] = random.randint(0, 500) if random.random() > 0.25 else None
        ev["aqi"] = random.randint(0, 300)

    # v1.3.0-beta adds debug payload (creates extra fields)
    if firmware == "v1.3.0-beta" and random.random() < 0.4:
        ev["debug"] = {
            "rssi": random.randint(-90, -40),
            "uptime_s": random.randint(0, 86400),
            "free_heap": random.randint(20000, 100000),
        }

    # Simulate occasional null storms (5% of events all readings null)
    if random.random() < 0.05:
        for k in list(ev.keys()):
            if k not in ("device_id", "sensor_type", "location", "firmware", "timestamp", "_ingested_at"):
                ev[k] = None

    return ev


def feed_iot(producer: KafkaProducer, topic: str, rate_hz: float = 5.0) -> None:
    log.info("[iot] starting (%d sensors, %.1f events/s)", 50, rate_hz)
    interval = 1.0 / rate_hz
    while True:
        publish(producer, topic, _iot_event())
        time.sleep(interval + random.uniform(-0.05, 0.05))


# ── Entry point ────────────────────────────────────────────────────────────────

FEEDS = {
    "wikipedia": (feed_wikipedia, "events.wikipedia"),
    "github":    (feed_github,    "events.github"),
    "payments":  (feed_payments,  "events.payments"),
    "bookings":  (feed_bookings,  "events.bookings"),
    "flights":   (feed_flights,   "events.flights"),
    "iot":       (feed_iot,       "events.iot"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed free public data into local Kafka")
    parser.add_argument("--brokers", default="localhost:9092")
    parser.add_argument(
        "--topics",
        default=",".join(FEEDS.keys()),
        help="Comma-separated list of feeds to run (default: all)",
    )
    args = parser.parse_args()

    selected = [t.strip() for t in args.topics.split(",") if t.strip() in FEEDS]
    if not selected:
        print(f"No valid feeds. Choose from: {', '.join(FEEDS)}")
        sys.exit(1)

    producer = make_producer(args.brokers)

    print(f"\n{'─'*60}")
    print("  StreamForge Kafka Demo — live data feeds")
    print(f"{'─'*60}")
    for name in selected:
        _, topic = FEEDS[name]
        print(f"  {name:<12} → {topic}")
    print(f"{'─'*60}")
    print("  payments drift kicks in after 5 min (watch for it!)")
    print("  Stop with Ctrl+C")
    print(f"{'─'*60}\n")

    threads = []
    for name in selected:
        fn, topic = FEEDS[name]
        t = threading.Thread(target=fn, args=(producer, topic), daemon=True, name=name)
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping feeds…")
        producer.flush(timeout=5)
        producer.close()


if __name__ == "__main__":
    main()
