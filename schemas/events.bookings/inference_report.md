# Inference Report — events.bookings

**Inferred:** 2026-03-19T16:04:50.267794+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Overall confidence:** 60%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 150 | 150 | 0 | 100.0% |

---

## Field Summary

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

---

## PII Fields

- **`passengers[].passenger_name`** — name
- **`passengers[].ticket_number`** — passport
- **`passengers[].passport_number`** — passport
- **`contact_email`** — email
- **`contact_phone`** — phone
- **`passengers[].frequent_flyer_number`** — loyalty_number
- **`passengers[].date_of_birth`** — phone, date_of_birth

---

## Low Confidence Fields (< 80%)

- **`booking_ref`** — 70% confidence — Statistically inferred (LLM fallback)
- **`event_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`airline`** — 70% confidence — Statistically inferred (LLM fallback)
- **`origin`** — 70% confidence — Statistically inferred (LLM fallback)
- **`destination`** — 70% confidence — Statistically inferred (LLM fallback)
- **`cabin`** — 70% confidence — Statistically inferred (LLM fallback)
- **`status`** — 70% confidence — Statistically inferred (LLM fallback)
- **`total_price`** — 70% confidence — Statistically inferred (LLM fallback)
- **`currency`** — 70% confidence — Statistically inferred (LLM fallback)
- **`created_at`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passengers`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passengers[].passenger_name`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passengers[].ticket_number`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passengers[].passport_number`** — 65% confidence — Statistically inferred (LLM fallback)
- **`contact_email`** — 61% confidence — Statistically inferred (LLM fallback)
- **`contact_phone`** — 58% confidence — Statistically inferred (LLM fallback)
- **`seat_preference`** — 54% confidence — Statistically inferred (LLM fallback)
- **`passengers[].frequent_flyer_number`** — 61% confidence — Statistically inferred (LLM fallback)
- **`baggage_allowance_kg`** — 56% confidence — Statistically inferred (LLM fallback)
- **`passengers[].date_of_birth`** — 58% confidence — Statistically inferred (LLM fallback)
- **`special_meal`** — 54% confidence — Statistically inferred (LLM fallback)
