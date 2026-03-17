# Inference Report — bookings.stream

**Inferred:** 2026-03-14T11:18:37.520943+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 250  
**Overall confidence:** 85%

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `booking_reference` | string | ✓ | 90% | — |
| `created_at` | mixed | ✓ | 80% | — |
| `total_price` | float | ✓ | 90% | — |
| `currency` | string | ✓ | 90% | — |
| `cabin_class` | string | ✓ | 90% | — |
| `contact_email` | email | ✓ | 90% | email |
| `contact_phone` | phone | ✓ | 90% | phone |
| `flights` | array | ✓ | 90% | — |
| `flights[]` | string | ✓ | 90% | — |
| `loyalty_number` | string | ○ | 80% | passport, loyalty_number |
| `passengers` | array | ○ | 80% | — |
| `passengers[].title` | string | ○ | 80% | — |
| `passengers[].first_name` | string | ○ | 80% | name |
| `passengers[].last_name` | string | ○ | 80% | name |
| `passengers[].date_of_birth` | string | ○ | 80% | date_of_birth, phone |
| `passengers[].passport_number` | string | ○ | 80% | passport |

---

## PII Fields

- **`contact_email`** — email
- **`contact_phone`** — phone
- **`loyalty_number`** — passport, loyalty_number
- **`passengers[].first_name`** — name
- **`passengers[].last_name`** — name
- **`passengers[].date_of_birth`** — date_of_birth, phone
- **`passengers[].passport_number`** — passport

---

## Mixed Type Fields

- **`created_at`** — Timestamp of event creation, sometimes in ISO8601 format and sometimes in Unix epoch milliseconds

---

## Rare Fields (< 10% presence)

- **`flights[]`** — present in 0% of events
