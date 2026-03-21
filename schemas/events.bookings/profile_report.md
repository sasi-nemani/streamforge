# Stream Profile Report — events.bookings

**Profiled:** 2026-03-19T16:04:50.267794+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 3

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `booking.created` | 57 | 38% | 21 | 60% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `booking.cancelled` | 52 | 35% | 21 | 60% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `booking.updated` | 41 | 27% | 21 | 60% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |

---

## `booking.created`

- **Events:** 57 (38% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `airline` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `cabin` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `total_price` | float | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 70% | — |
| `passengers[].passenger_name` | string | ✓ | 70% | name |
| `passengers[].ticket_number` | string | ✓ | 70% | passport |
| `passengers[].passport_number` | string | ○ | 65% | passport |
| `contact_email` | string | ○ | 61% | email |
| `contact_phone` | string | ○ | 58% | phone |
| `seat_preference` | string | ○ | 54% | — |
| `passengers[].frequent_flyer_number` | string | ○ | 61% | loyalty_number |
| `baggage_allowance_kg` | integer | ○ | 56% | — |
| `passengers[].date_of_birth` | string | ○ | 58% | phone, date_of_birth |
| `special_meal` | string | ○ | 54% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `passengers[].frequent_flyer_number` (loyalty_number), `passengers[].date_of_birth` (phone, date_of_birth)

---

## `booking.cancelled`

- **Events:** 52 (35% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `airline` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `cabin` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `total_price` | float | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 70% | — |
| `passengers[].passenger_name` | string | ✓ | 70% | name |
| `passengers[].ticket_number` | string | ✓ | 70% | passport |
| `passengers[].passport_number` | string | ○ | 65% | passport |
| `passengers[].frequent_flyer_number` | string | ○ | 62% | loyalty_number |
| `contact_email` | string | ○ | 60% | email |
| `seat_preference` | string | ○ | 55% | — |
| `special_meal` | string | ○ | 53% | — |
| `passengers[].date_of_birth` | string | ○ | 60% | phone, date_of_birth |
| `baggage_allowance_kg` | integer | ○ | 56% | — |
| `contact_phone` | string | ○ | 56% | phone |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].frequent_flyer_number` (loyalty_number), `contact_email` (email), `passengers[].date_of_birth` (phone, date_of_birth), `contact_phone` (phone)

---

## `booking.updated`

- **Events:** 41 (27% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `airline` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `cabin` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `total_price` | float | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 70% | — |
| `passengers[].passenger_name` | string | ✓ | 70% | name |
| `passengers[].ticket_number` | string | ✓ | 70% | passport |
| `passengers[].passport_number` | string | ○ | 64% | passport |
| `passengers[].date_of_birth` | string | ○ | 61% | phone, date_of_birth |
| `passengers[].frequent_flyer_number` | string | ○ | 62% | loyalty_number |
| `contact_email` | string | ○ | 59% | email |
| `contact_phone` | string | ○ | 56% | phone |
| `baggage_allowance_kg` | integer | ○ | 59% | — |
| `seat_preference` | string | ○ | 55% | — |
| `special_meal` | string | ○ | 54% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].date_of_birth` (phone, date_of_birth), `passengers[].frequent_flyer_number` (loyalty_number), `contact_email` (email), `contact_phone` (phone)
