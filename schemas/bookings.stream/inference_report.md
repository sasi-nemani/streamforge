# Inference Report — bookings.stream

**Inferred:** 2026-03-24T13:30:16.734785+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 200  
**Overall confidence:** 60%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 250 | 250 | 0 | 100.0% |

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `booking_reference` | string | ✓ | 70% | — |
| `created_at` | mixed | ✓ | 70% | — |
| `total_price` | mixed | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `cabin_class` | string | ✓ | 70% | — |
| `passengers` | array | ✓ | 69% | — |
| `passengers[].title` | string | ✓ | 69% | — |
| `passengers[].first_name` | string | ✓ | 69% | name |
| `passengers[].last_name` | string | ✓ | 69% | name |
| `passengers[].date_of_birth` | string | ✓ | 69% | date_of_birth, phone |
| `passengers[].passport_number` | string | ✓ | 69% | passport |
| `contact_email` | email | ✓ | 97% | email |
| `contact_phone` | string | ✓ | 70% | phone |
| `flights` | array | ✓ | 70% | — |
| `loyalty_number` | string | ✓ | 70% | loyalty_number, passport |
| `passenger_name` | string | ○ | 51% | name |

---

## PII Fields

- **`passengers[].first_name`** — name
- **`passengers[].last_name`** — name
- **`passengers[].date_of_birth`** — date_of_birth, phone
- **`passengers[].passport_number`** — passport
- **`contact_email`** — email
- **`contact_phone`** — phone
- **`loyalty_number`** — loyalty_number, passport
- **`passenger_name`** — name

---

## Low Confidence Fields (< 80%)

- **`event_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`booking_reference`** — 70% confidence — Statistically inferred (LLM fallback)
- **`created_at`** — 70% confidence — Statistically inferred (LLM fallback)
- **`total_price`** — 70% confidence — Statistically inferred (LLM fallback)
- **`currency`** — 70% confidence — Statistically inferred (LLM fallback)
- **`cabin_class`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passengers`** — 69% confidence — Statistically inferred (LLM fallback)
- **`passengers[].title`** — 69% confidence — Statistically inferred (LLM fallback)
- **`passengers[].first_name`** — 69% confidence — Statistically inferred (LLM fallback)
- **`passengers[].last_name`** — 69% confidence — Statistically inferred (LLM fallback)
- **`passengers[].date_of_birth`** — 69% confidence — Statistically inferred (LLM fallback)
- **`passengers[].passport_number`** — 69% confidence — Statistically inferred (LLM fallback)
- **`contact_phone`** — 70% confidence — Statistically inferred (LLM fallback)
- **`flights`** — 70% confidence — Statistically inferred (LLM fallback)
- **`loyalty_number`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passenger_name`** — 51% confidence — Statistically inferred (LLM fallback)

---

## Mixed Type Fields

- **`created_at`** — Statistically inferred (LLM fallback)
- **`total_price`** — Statistically inferred (LLM fallback)

---

## Rare Fields (< 10% presence)

- **`passenger_name`** — present in 7% of events
