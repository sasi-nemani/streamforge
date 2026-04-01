#!/usr/bin/env python3
"""
inject_drift.py — Deterministically inject drifted payment events into Kafka.

Every event has ALL drift mutations applied — no randomness that could weaken detection:
  - amount_minor_units (int)    replaces  amount (float)      → type change
  - timestamp is ISO8601 string replaces  epoch ms integer    → format change
  - card_last_four (str)        NEW field                     → new PII (Tier 3)
  - status is 0/1/2/3 (int)    replaces  "pending"/... str   → type change
  - amount field is absent                                    → field removed (Tier 3)

50 events guarantees >5% drift rate in any 200-event sample window.
With 500 pre-seeded clean events: 50 / 550 ≈ 9% rate — well above the 5% threshold.

Usage:
  python3 demo/inject_drift.py
  python3 demo/inject_drift.py --count 50 --brokers localhost:9092
"""

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

DEFAULT_TOPIC = "events.payments"
_MERCHANTS = ["stripe", "adyen", "checkout", "braintree", "square"]
_CURRENCIES = ["USD", "EUR", "GBP", "SGD", "AUD", "JPY"]


def make_producer(brokers: str) -> KafkaProducer:
    for attempt in range(10):
        try:
            return KafkaProducer(
                bootstrap_servers=brokers,
                value_serializer=lambda v: json.dumps(v).encode(),
            )
        except NoBrokersAvailable:
            print(f"  Kafka not ready, retrying ({attempt + 1}/10)…")
            time.sleep(2)
    print(f"ERROR: Cannot connect to Kafka at {brokers}")
    sys.exit(1)


def drifted_payment_event(i: int) -> dict:
    """
    Return a fully drifted payment event.

    ALL mutations are applied deterministically — no random branching.
    This guarantees every injected event registers as drift.
    """
    return {
        "_type": "payment",
        "event_id": str(uuid.uuid4()),
        "event_type": ["payment.created", "payment.updated", "payment.failed"][i % 3],
        "user_id": f"u_{1000 + i}",
        "merchant": _MERCHANTS[i % len(_MERCHANTS)],
        "currency": _CURRENCIES[i % len(_CURRENCIES)],

        # DRIFT: status changed from string to integer
        "status": i % 4,

        # DRIFT: amount replaced by amount_minor_units (field removed + new field)
        "amount_minor_units": 100 + (i * 97 % 99900),

        # DRIFT: timestamp format changed from epoch ms to ISO8601 string
        "timestamp": datetime.now(UTC).isoformat(),

        # DRIFT: new PII field (card_last_four) — triggers Tier 3
        "card_last_four": f"{1000 + (i * 37 % 9000)}",

        "_ingested_at": datetime.now(UTC).isoformat(),
        "_drift_injected": True,   # marker so you can filter in Kafka UI
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject drifted payment events for demo")
    parser.add_argument("--brokers", default="localhost:9092")
    parser.add_argument("--count", type=int, default=50,
                        help="Number of drifted events to inject (default: 50)")
    parser.add_argument("--topic", default=DEFAULT_TOPIC,
                        help=f"Kafka topic to inject into (default: {DEFAULT_TOPIC})")
    args = parser.parse_args()

    print(f"Injecting {args.count} drifted payment events into {args.topic}…")
    producer = make_producer(args.brokers)

    for i in range(args.count):
        event = drifted_payment_event(i)
        producer.send(args.topic, event, key=b"payment")

    producer.flush(timeout=10)
    producer.close()

    print(f"✓ Injected {args.count} drifted events.")
    print("  Mutations applied to every event:")
    print("    • amount (float) → REMOVED")
    print("    • amount_minor_units (int) → ADDED  [field change]")
    print("    • timestamp: epoch ms → ISO8601 string  [type change]")
    print("    • card_last_four: NEW PII field  [Tier 3]")
    print("    • status: string → integer  [type change]")
    print()
    print("  StreamForge watch will detect drift within the next poll cycle (~5-10s).")


if __name__ == "__main__":
    main()
