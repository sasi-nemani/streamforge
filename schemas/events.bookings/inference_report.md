# Inference Report — events.bookings

**Inferred:** 2026-03-24T11:31:30.447586+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Overall confidence:** 92%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 400 | 400 | 0 | 100.0% |

---

## Field Summary

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

---

## PII Fields

- **`passengers[].passenger_name`** — name
- **`passengers[].ticket_number`** — passport
- **`passengers[].passport_number`** — passport
- **`passengers[].frequent_flyer_number`** — loyalty_number
- **`contact_email`** — email
- **`passengers[].date_of_birth`** — phone, date_of_birth
- **`contact_phone`** — phone
