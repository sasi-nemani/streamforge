"""
streamforge/connectors/generators.py — Realistic Event Generators for Demo
===========================================================================

Generates deterministic, realistic event streams for the demo command.
Two phases:

  Phase 1 — payment_events(n=300)
    Clean baseline: epoch_ms timestamps, integer amount, no PII beyond email.
    Represents a well-behaved production stream before a bad deploy.

  Phase 2 — drifted_payment_events(n=200)
    Simulates the breaking change that fires at 2:17am:
      [TIER 3] amount          → field removed (was 100% present)
      [TIER 3] amount_minor_units → new required field (integer cents, not dollars)
      [TIER 2] timestamp       → epoch_ms → ISO8601 format change (100% of events)
      [TIER 3] card_last_four  → new PII field (card_number category)
      [TIER 1] user_name       → new optional PII field (name category)

Design:
  - Seeded random for reproducibility (same events every demo run)
  - Human-legible values (real-looking emails, merchant IDs, amounts)
  - Used by MockConnector in the `streamforge demo` command
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

# ── Fixture pools ──────────────────────────────────────────────────────────────

_USER_EMAILS = [
    "alice.johnson@acmecorp.com",
    "bob.smith@enterprise.io",
    "carol.white@startup.ai",
    "david.chen@bigbank.com",
    "eva.martinez@payments.io",
    "frank.liu@techco.com",
    "grace.kim@retailplus.com",
    "henry.osei@fintech.ng",
]

_USER_NAMES = [
    "Alice Johnson",
    "Bob Smith",
    "Carol White",
    "David Chen",
    "Eva Martinez",
    "Frank Liu",
    "Grace Kim",
    "Henry Osei",
]

_MERCHANTS = [
    "merch_stripe_001",
    "merch_paypal_007",
    "merch_adyen_042",
    "merch_braintree_013",
    "merch_checkout_099",
    "merch_worldpay_055",
]

_CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD"]

_EVENT_TYPES = [
    "payment_initiated",
    "payment_completed",
    "payment_failed",
]

# Weighted so payment_initiated is most common (realistic)
_EVENT_TYPE_WEIGHTS = [0.50, 0.38, 0.12]

_STATUSES = ["pending", "completed", "failed", "processing"]

_CARD_LAST_FOURS = ["4242", "5555", "3782", "6011", "1111", "9999", "7777"]

# Base timestamp: March 14 2026 00:00:00 UTC (demo day)
_BASE_TS_MS = int(datetime(2026, 3, 14, tzinfo=UTC).timestamp() * 1000)
_BASE_TS_DT = datetime(2026, 3, 14, tzinfo=UTC)


def _make_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


# ── Phase 1: Clean baseline events ────────────────────────────────────────────

def payment_events(n: int = 300, seed: int = 42) -> list[dict]:
    """
    Generate n clean payment events — the baseline schema.

    Schema produced:
      event_id          uuid        required  100%
      event_type        string/enum required  100%  [payment_initiated, payment_completed, payment_failed]
      timestamp         integer     required  100%  epoch_ms (~13 digits)
      amount            float       required  100%  dollars.cents
      currency          string/enum required  100%  [USD, EUR, GBP, CAD, AUD]
      user_id           uuid        required  100%
      user_email        email       required  100%  PII: email
      merchant_id       string      required  100%
      status            string/enum required  100%
      metadata.source   string      optional  72%   ["web", "mobile", "api"]
      metadata.version  string      optional  65%   ["v2", "v3"]
    """
    rng = random.Random(seed)
    events = []

    for _ in range(n):
        offset_ms = rng.randint(0, 86_400_000 * 13)  # spread over 13 days
        ts_ms = _BASE_TS_MS - offset_ms  # events before demo day

        event: dict = {
            "event_id":    _make_uuid(rng),
            "event_type":  rng.choices(_EVENT_TYPES, weights=_EVENT_TYPE_WEIGHTS, k=1)[0],
            "timestamp":   ts_ms,
            "amount":      round(rng.uniform(1.00, 2499.99), 2),
            "currency":    rng.choice(_CURRENCIES),
            "user_id":     _make_uuid(rng),
            "user_email":  rng.choice(_USER_EMAILS),
            "merchant_id": rng.choice(_MERCHANTS),
            "status":      rng.choice(_STATUSES),
        }

        # Optional metadata sub-object (72% presence)
        if rng.random() < 0.72:
            event["metadata"] = {
                "source":  rng.choice(["web", "mobile", "api"]),
                "version": rng.choice(["v2", "v3"]) if rng.random() < 0.65 else None,
            }

        events.append(event)

    return events


# ── Phase 2: Drifted events — the 2:17am breaking change ──────────────────────

def drifted_payment_events(n: int = 200, seed: int = 99) -> list[dict]:
    """
    Generate n drifted payment events — simulates a breaking deploy.

    Drift introduced vs. baseline schema:
      [TIER 3] amount           → REMOVED (was 100% present)
      [TIER 3] amount_minor_units → NEW required field (integer cents)
                                    e.g. $24.99 → 2499
      [TIER 2] timestamp        → FORMAT CHANGED epoch_ms → ISO8601 string
      [TIER 3] card_last_four   → NEW PII field (4-digit string, card_number)
      [TIER 1] user_name        → NEW optional PII field (full name, name category)

    This matches the board-room demo script:
      "Someone changed `amount` at 2:17am. Four engineers. Six hours."
    """
    rng = random.Random(seed)
    events = []

    for _ in range(n):
        # Timestamps now ISO8601 — the Tier 2 format drift
        offset_s = rng.randint(0, 3600 * 4)  # events within 4h window around 2am
        ts_dt = _BASE_TS_DT + timedelta(hours=2, minutes=17, seconds=offset_s)
        ts_iso = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        amount_dollars = round(rng.uniform(1.00, 2499.99), 2)
        amount_minor   = int(amount_dollars * 100)  # dollars → integer cents

        event: dict = {
            "event_id":           _make_uuid(rng),
            "event_type":         rng.choices(
                                    ["payment_initiated", "payment_completed"],
                                    weights=[0.55, 0.45], k=1
                                  )[0],
            "timestamp":          ts_iso,            # DRIFT: epoch_ms → ISO8601
            # "amount" intentionally absent          # DRIFT: required field removed
            "amount_minor_units": amount_minor,      # DRIFT: new required field
            "currency":           rng.choice(_CURRENCIES),
            "user_id":            _make_uuid(rng),
            "user_email":         rng.choice(_USER_EMAILS),
            "merchant_id":        rng.choice(_MERCHANTS),
            "status":             rng.choice(["pending", "completed", "processing"]),
            "card_last_four":     rng.choice(_CARD_LAST_FOURS),  # DRIFT: new PII field
        }

        # user_name — new optional PII field, 78% presence
        if rng.random() < 0.78:
            event["user_name"] = rng.choice(_USER_NAMES)  # DRIFT: new PII name field

        # metadata still present but version field gone
        if rng.random() < 0.70:
            event["metadata"] = {
                "source":  rng.choice(["web", "mobile", "api"]),
            }

        events.append(event)

    return events


# ── Convenience: stream spec for MockConnector ─────────────────────────────────

def payment_demo_phases():
    """
    Return (baseline_events, drifted_events) ready for MockConnector phases.

    Usage:
        from streamforge.connectors.generators import payment_demo_phases
        from streamforge.connectors.mock import MockConnector, DriftPhase

        baseline, drifted = payment_demo_phases()
        connector = MockConnector(phases=[
            DriftPhase(events=baseline, label="baseline — clean schema"),
            DriftPhase(events=drifted, label="drift: 2am breaking deploy"),
        ], events_per_second=50.0)
    """
    return payment_events(n=300, seed=42), drifted_payment_events(n=200, seed=99)
