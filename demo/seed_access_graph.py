#!/usr/bin/env python3
"""Seed the observed access graph by running realistic consumers over bundled events.

This simulates what happens in production: each consumer service processes messages
and reads the fields it needs. StreamForge's ConsumerObserver records exactly which
fields each one touches — building observed lineage with no manifest and no
producer changes. Run it, then open the cockpit blast-radius panel.

    python3 demo/seed_access_graph.py
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

from streamforge.access_observer import ConsumerObserver, ObservedAccessStore

ROOT = Path(__file__).resolve().parents[1]

# topic (matches the schema dir name) -> events folder on disk
TOPICS = {
    "events.payments": ROOT / "events" / "payments" / "stream_v1",
    "events.bookings": ROOT / "events" / "bookings" / "stream",
    "events.iot": ROOT / "events" / "iot" / "stream",
}


def _events(folder: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(folder.glob("*.ndjson")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    out.append(json.loads(line))
    return out


# Each consumer is a real handler that reads the fields it depends on. The observer
# records what it touches — nothing more. (Note: handlers deliberately do NOT read
# every field, so the observed graph reflects true dependencies.)
CONSUMERS: dict[str, dict] = {
    "events.payments": {
        "fraud-detection-service": lambda e: (
            e.get("amount"), e.get("currency"), e.get("status"),
            e.get("payment_method"), (e.get("user") or {}).get("user_id"),
        ),
        "ledger-sync": lambda e: (
            e.get("transaction_id"), e.get("amount"), e.get("currency"),
        ),
        "analytics-warehouse": lambda e: (
            e.get("amount"), e.get("payment_method"), e.get("timestamp"),
        ),
    },
    "events.bookings": {
        "revenue-reporting": lambda e: (
            e.get("total_price"), e.get("currency"), e.get("cabin_class"),
        ),
        "passenger-manifest": lambda e: [
            (p.get("passport_number"), p.get("date_of_birth"), p.get("last_name"))
            for p in (e.get("passengers") or [])
        ],
        "loyalty-engine": lambda e: (
            e.get("loyalty_number"), e.get("contact_email"),
        ),
    },
    "events.iot": {
        "realtime-alerting": lambda e: (
            e.get("value"), e.get("sensor_type"), e.get("anomaly"),
        ),
        "ops-dashboard": lambda e: (
            e.get("value"), e.get("timestamp"), e.get("battery_level"),
        ),
    },
}


def main() -> None:
    store = ObservedAccessStore()  # fresh; compounds if you point at an existing one
    for topic, folder in TOPICS.items():
        if not folder.is_dir():
            print(f"  skip {topic}: no events at {folder}")
            continue
        events = _events(folder)
        for consumer, handler in CONSUMERS.get(topic, {}).items():
            obs = ConsumerObserver(consumer, topic, store=store)
            for ev in events:
                obs.observe(ev, handler)
            print(f"  {topic:18s} · {consumer:22s} observed over {len(events)} events")

    out = ROOT / ".streamforge" / "access_graph.json"
    store.save(out)
    s = store.stats()
    print(f"\nObserved access graph → {out}")
    print(f"  {s['topics']} topics · {s['consumers']} consumers · {s['field_edges']} field-level edges")


if __name__ == "__main__":
    main()
