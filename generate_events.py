"""
StreamForge MVP — Event Data Generator
Generates realistic, intentionally messy JSON event streams
simulating what you'd actually find in a production Kafka topic.

Intentional messiness baked in:
- Mixed timestamp formats (epoch ms, ISO8601, RFC2822)
- Fields that appear/disappear inconsistently
- Type inconsistencies (amount as string vs float)
- PII fields (emails, names, card-like numbers)
- Nested vs flat structure inconsistency
- Enum fields with occasional typos/variants
- Null vs missing field inconsistency
- Schema drift in later files (simulates prod drift over time)
"""

import json
import random
import uuid
import os
from datetime import datetime, timedelta

random.seed(42)

def rand_timestamp(fmt="epoch"):
    base = datetime(2026, 1, 1) + timedelta(seconds=random.randint(0, 7776000))
    if fmt == "epoch":
        return int(base.timestamp() * 1000)
    elif fmt == "iso":
        return base.isoformat() + "Z"
    elif fmt == "rfc":
        return base.strftime("%a, %d %b %Y %H:%M:%S GMT")
    elif fmt == "date":
        return base.strftime("%Y-%m-%d")

def maybe(val, prob=0.85):
    return val if random.random() < prob else None

def sometimes_missing(d, key, val, prob=0.85):
    if random.random() < prob:
        d[key] = val

# ─── PAYMENTS EVENTS ──────────────────────────────────────────────────────────

def payment_event_v1():
    """Clean-ish payments — first 300 events"""
    statuses = ["COMPLETED", "COMPLETED", "COMPLETED", "FAILED", "PENDING"]
    currencies = ["GBP", "USD", "EUR", "GBP", "GBP"]
    methods = ["CARD", "APPLE_PAY", "BANK_TRANSFER", "CARD", "GOOGLE_PAY"]
    
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "payment.processed",
        "timestamp": rand_timestamp("epoch"),
        "transaction_id": f"TXN-{random.randint(100000, 999999)}",
        "amount": round(random.uniform(1.0, 5000.0), 2),
        "currency": random.choice(currencies),
        "status": random.choice(statuses),
        "payment_method": random.choice(methods),
        "user": {
            "user_id": f"USR-{random.randint(1000, 9999)}",
            "email": f"user{random.randint(1,5000)}@example.com",
            "name": random.choice(["Alice Smith", "Bob Jones", "Carol White", "Dave Brown"]),
        },
        "metadata": {
            "ip_address": f"192.168.{random.randint(1,254)}.{random.randint(1,254)}",
            "user_agent": "Mozilla/5.0",
            "region": random.choice(["UK", "US", "EU"]),
        }
    }
    
    # Occasional: amount comes as string (type inconsistency)
    if random.random() < 0.08:
        event["amount"] = str(event["amount"])
    
    # Occasional: missing metadata
    if random.random() < 0.1:
        del event["metadata"]
    
    # Occasional: flat user instead of nested
    if random.random() < 0.05:
        user = event.pop("user")
        event["user_id"] = user["user_id"]
        event["user_email"] = user["email"]
    
    return event


def payment_event_v2_drift():
    """
    Drifted payments — simulates schema change that happened in production:
    - timestamp changed from epoch_ms to ISO8601
    - amount renamed to amount_minor_units (pence, not pounds)
    - new field: merchant_id added
    - status values changed: COMPLETED→SUCCESS, FAILED→DECLINED
    - card_last_four appears (new PII field)
    """
    statuses_new = ["SUCCESS", "SUCCESS", "SUCCESS", "DECLINED", "PENDING", "REFUNDED"]
    
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "payment.processed",
        "timestamp": rand_timestamp("iso"),          # DRIFT: was epoch, now ISO
        "transaction_id": f"TXN-{random.randint(100000, 999999)}",
        "amount_minor_units": random.randint(100, 500000),  # DRIFT: renamed + unit change
        "currency": random.choice(["GBP", "USD", "EUR"]),
        "status": random.choice(statuses_new),       # DRIFT: enum values changed
        "payment_method": random.choice(["CARD", "APPLE_PAY", "BANK_TRANSFER"]),
        "merchant_id": f"MER-{random.randint(100, 999)}",  # NEW field
        "card_last_four": str(random.randint(1000, 9999)) if random.random() < 0.6 else None,  # NEW PII
        "user": {
            "user_id": f"USR-{random.randint(1000, 9999)}",
            "email": f"user{random.randint(1,5000)}@example.com",
            "name": random.choice(["Alice Smith", "Bob Jones", "Carol White"]),
        },
        "metadata": {
            "region": random.choice(["UK", "US", "EU"]),
        }
    }
    return event


# ─── FLIGHT EVENTS ────────────────────────────────────────────────────────────

def flight_event():
    airlines = ["BA", "LH", "AF", "EK", "QF"]
    statuses = ["ON_TIME", "DELAYED", "CANCELLED", "BOARDING", "DEPARTED", "LANDED"]
    airports = ["LHR", "LGW", "MAN", "EDI", "CDG", "FRA", "JFK", "DXB"]
    
    delay_mins = random.randint(0, 240) if random.random() < 0.3 else 0
    
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": random.choice([
            "flight.status_changed", "flight.gate_changed",
            "flight.departed", "flight.landed", "flight.delayed"
        ]),
        "flight_number": f"{random.choice(airlines)}{random.randint(100, 9999)}",
        "origin": random.choice(airports),
        "destination": random.choice(airports),
        "scheduled_departure": rand_timestamp("iso"),
        "actual_departure": rand_timestamp("iso") if random.random() < 0.7 else None,
        "delay_minutes": delay_mins,
        "status": random.choice(statuses),
        "gate": f"{random.choice('ABCDEFGH')}{random.randint(1,50)}" if random.random() < 0.8 else None,
        "aircraft_type": random.choice(["A320", "B737", "A380", "B777", "A350"]),
        "passenger_count": random.randint(50, 450) if random.random() < 0.6 else None,
        "timestamp": rand_timestamp(random.choice(["epoch", "iso"])),  # Mixed formats
    }
    
    # Occasional: severity field (appears in ~30% of events)
    if random.random() < 0.3:
        event["severity"] = random.choice(["INFO", "WARNING", "CRITICAL"])
    
    # Occasional: crew info (appears in ~20%)
    if random.random() < 0.2:
        event["crew_captain"] = random.choice(["Capt. James", "Capt. Sarah", "Capt. Ahmed"])
    
    # Type drift: delay_minutes sometimes comes as string
    if random.random() < 0.07:
        event["delay_minutes"] = str(event["delay_minutes"])
    
    return event


# ─── BOOKING EVENTS ───────────────────────────────────────────────────────────

def booking_event():
    classes = ["ECONOMY", "BUSINESS", "FIRST", "ECONOMY", "ECONOMY"]
    
    num_passengers = random.randint(1, 6)
    passengers = []
    for _ in range(num_passengers):
        p = {
            "title": random.choice(["Mr", "Mrs", "Ms", "Dr"]),
            "first_name": random.choice(["James", "Sarah", "Ahmed", "Priya", "Tom"]),
            "last_name": random.choice(["Smith", "Jones", "Patel", "Kumar", "White"]),
            "date_of_birth": rand_timestamp("date"),
            "passport_number": f"{random.choice('ABCDEFGH')}{random.randint(10000000, 99999999)}" if random.random() < 0.7 else None,
        }
        passengers.append(p)
    
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": random.choice([
            "booking.created", "booking.amended",
            "booking.cancelled", "booking.check_in"
        ]),
        "booking_reference": f"{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=6))}",
        "created_at": rand_timestamp(random.choice(["epoch", "iso", "rfc"])),  # 3 formats!
        "total_price": round(random.uniform(50, 8000), 2),
        "currency": random.choice(["GBP", "USD", "EUR"]),
        "cabin_class": random.choice(classes),
        "passengers": passengers,
        "contact_email": f"passenger{random.randint(1,9999)}@gmail.com",
        "contact_phone": f"+44{random.randint(7000000000, 7999999999)}",
        "flights": [
            f"{random.choice(['BA','LH','AF'])}{random.randint(100,999)}"
            for _ in range(random.randint(1, 3))
        ],
        "loyalty_number": f"BA{random.randint(100000000, 999999999)}" if random.random() < 0.4 else None,
    }
    
    # Occasional: flat passenger for single-pax bookings (structural inconsistency)
    if num_passengers == 1 and random.random() < 0.2:
        p = event["passengers"][0]
        event["passenger_name"] = f"{p['first_name']} {p['last_name']}"
        del event["passengers"]
    
    # Occasional: price as string
    if random.random() < 0.05:
        event["total_price"] = f"{event['total_price']:.2f}"
    
    return event


# ─── IoT / SENSOR EVENTS ──────────────────────────────────────────────────────

def iot_event():
    sensor_types = ["TEMPERATURE", "PRESSURE", "HUMIDITY", "VIBRATION", "FUEL"]
    locations = ["GATE_A1", "RUNWAY_27L", "HANGAR_3", "TERMINAL_2", "APRON_B"]
    
    event = {
        "sensor_id": f"SNS-{random.randint(1000, 9999)}",
        "sensor_type": random.choice(sensor_types),
        "location": random.choice(locations),
        "value": round(random.uniform(-40, 150), 3),
        "unit": random.choice(["celsius", "hPa", "percent", "g-force", "litres"]),
        "timestamp": rand_timestamp(random.choice(["epoch", "iso"])),
        "battery_level": random.randint(0, 100) if random.random() < 0.7 else None,
        "signal_strength": random.randint(-100, 0),
        "anomaly": random.random() < 0.05,
    }
    
    # Occasional: value as string (firmware bug simulation)
    if random.random() < 0.06:
        event["value"] = str(event["value"])
    
    # Occasional: nested reading vs flat
    if random.random() < 0.15:
        event["reading"] = {"value": event.pop("value"), "unit": event.pop("unit")}
    
    # Occasional: alert field on anomaly events
    if event.get("anomaly"):
        event["alert_level"] = random.choice(["LOW", "MEDIUM", "HIGH"])
        event["alert_message"] = f"Sensor {event['sensor_id']} reading out of normal range"
    
    return event


# ─── GENERATE FILES ───────────────────────────────────────────────────────────

def write_events(path, events, batch_size=50):
    """Write events as NDJSON files (one JSON object per line — common log format)"""
    os.makedirs(path, exist_ok=True)
    batches = [events[i:i+batch_size] for i in range(0, len(events), batch_size)]
    for i, batch in enumerate(batches):
        fname = os.path.join(path, f"events_{i:04d}.ndjson")
        with open(fname, "w") as f:
            for event in batch:
                f.write(json.dumps(event) + "\n")
    print(f"  ✓ {len(events)} events → {len(batches)} files in {path}")


def main():
    print("Generating StreamForge MVP test event data...\n")

    # Payments: 300 clean-ish + 200 drifted (in separate subfolder to simulate drift over time)
    payments_clean = [payment_event_v1() for _ in range(300)]
    payments_drifted = [payment_event_v2_drift() for _ in range(200)]
    write_events("events/payments/stream_v1", payments_clean)
    write_events("events/payments/stream_v2_drift", payments_drifted)

    # Flights: 400 events, naturally messy
    flights = [flight_event() for _ in range(400)]
    write_events("events/flights/stream", flights)

    # Bookings: 250 events with heavy PII
    bookings = [booking_event() for _ in range(250)]
    write_events("events/bookings/stream", bookings)

    # IoT: 500 sensor events, high volume
    iot = [iot_event() for _ in range(500)]
    write_events("events/iot/stream", iot)

    print(f"\nTotal: 1,650 events across 4 streams")
    print("Intentional issues baked in:")
    print("  - payments/stream_v2_drift: timestamp, amount rename, status enum drift, new PII field")
    print("  - bookings: 3 different timestamp formats, structural inconsistency in passengers")
    print("  - flights: mixed timestamp formats, optional fields, type drift on delay_minutes")
    print("  - iot: firmware-bug string values, nested vs flat reading structure")
    print("\nReady for streamforge init .")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
