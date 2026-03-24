# Stream Profile Report — events.bookings

**Profiled:** 2026-03-24T11:31:30.447586+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 3

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `booking.created` | 143 | 36% | 19 | 92% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `booking.cancelled` | 131 | 33% | 19 | 95% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `booking.updated` | 126 | 32% | 19 | 98% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |

---

## `booking.created`

- **Events:** 143 (36% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 92%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 95% | — |
| `event_type` | string | ✓ | 95% | — |
| `airline` | string | ✓ | 95% | — |
| `origin` | string | ✓ | 95% | — |
| `destination` | string | ✓ | 95% | — |
| `cabin` | string | ✓ | 95% | — |
| `status` | string | ✓ | 95% | — |
| `total_price` | float | ✓ | 95% | — |
| `currency` | string | ✓ | 95% | — |
| `created_at` | timestamp_iso8601 | ✓ | 99% | — |
| `passengers` | array | ✓ | 95% | — |
| `passengers[].passenger_name` | string | ✓ | 95% | name |
| `passengers[].ticket_number` | string | ✓ | 95% | passport |
| `passengers[].passport_number` | string | ○ | 85% | passport |
| `passengers[].frequent_flyer_number` | string | ○ | 85% | loyalty_number |
| `contact_email` | email | ○ | 97% | email |
| `passengers[].date_of_birth` | date | ○ | 85% | phone, date_of_birth |
| `contact_phone` | string | ○ | 85% | phone |
| `baggage_allowance_kg` | integer | ○ | 85% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].frequent_flyer_number` (loyalty_number), `contact_email` (email), `passengers[].date_of_birth` (phone, date_of_birth), `contact_phone` (phone)

---

## `booking.cancelled`

- **Events:** 131 (33% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 95%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 100% | — |
| `event_type` | string | ✓ | 100% | — |
| `airline` | string | ✓ | 100% | — |
| `origin` | string | ✓ | 100% | — |
| `destination` | string | ✓ | 100% | — |
| `cabin` | string | ✓ | 100% | — |
| `status` | string | ✓ | 100% | — |
| `total_price` | float | ✓ | 100% | — |
| `currency` | string | ✓ | 100% | — |
| `created_at` | timestamp_iso8601 | ✓ | 100% | — |
| `passengers` | array | ✓ | 100% | — |
| `passengers[].passenger_name` | string | ✓ | 100% | name |
| `passengers[].ticket_number` | string | ✓ | 100% | passport |
| `passengers[].passport_number` | string | ○ | 90% | passport |
| `passengers[].frequent_flyer_number` | string | ○ | 90% | loyalty_number |
| `passengers[].date_of_birth` | date | ○ | 90% | phone, date_of_birth |
| `contact_email` | email | ○ | 97% | email |
| `contact_phone` | string | ○ | 90% | phone |
| `baggage_allowance_kg` | integer | ○ | 90% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].frequent_flyer_number` (loyalty_number), `passengers[].date_of_birth` (phone, date_of_birth), `contact_email` (email), `contact_phone` (phone)

---

## `booking.updated`

- **Events:** 126 (32% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 98%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `booking_ref` | string | ✓ | 99% | — |
| `event_type` | string | ✓ | 99% | — |
| `airline` | string | ✓ | 99% | — |
| `origin` | string | ✓ | 99% | — |
| `destination` | string | ✓ | 99% | — |
| `cabin` | string | ✓ | 99% | — |
| `status` | string | ✓ | 99% | — |
| `total_price` | float | ✓ | 99% | — |
| `currency` | string | ✓ | 99% | — |
| `created_at` | timestamp_iso8601 | ✓ | 99% | — |
| `passengers` | array | ✓ | 99% | — |
| `passengers[].passenger_name` | string | ✓ | 99% | name |
| `passengers[].ticket_number` | string | ✓ | 99% | passport |
| `passengers[].passport_number` | string | ○ | 99% | passport |
| `passengers[].date_of_birth` | string | ○ | 99% | phone, date_of_birth |
| `passengers[].frequent_flyer_number` | string | ○ | 99% | loyalty_number |
| `contact_email` | email | ○ | 99% | email |
| `contact_phone` | string | ○ | 99% | phone |
| `baggage_allowance_kg` | integer | ○ | 99% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].date_of_birth` (phone, date_of_birth), `passengers[].frequent_flyer_number` (loyalty_number), `contact_email` (email), `contact_phone` (phone)
