# Inference Report — flights.stream

**Inferred:** 2026-03-13T21:52:58.091882+00:00  
**Model:** llama-3.3-70b-versatile(statistical-fallback)  
**Events sampled:** 200  
**Overall confidence:** 60%

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `flight_number` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `scheduled_departure` | string | ✓ | 70% | — |
| `actual_departure` | string | ✓ | 70% | — |
| `delay_minutes` | mixed | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `gate` | string | ✓ | 70% | — |
| `aircraft_type` | string | ✓ | 70% | — |
| `passenger_count` | integer | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `severity` | string | ○ | 57% | — |
| `crew_captain` | string | ○ | 54% | — |

---

## Low Confidence Fields (< 80%)

- **`event_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`event_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`flight_number`** — 70% confidence — Statistically inferred (LLM fallback)
- **`origin`** — 70% confidence — Statistically inferred (LLM fallback)
- **`destination`** — 70% confidence — Statistically inferred (LLM fallback)
- **`scheduled_departure`** — 70% confidence — Statistically inferred (LLM fallback)
- **`actual_departure`** — 70% confidence — Statistically inferred (LLM fallback)
- **`delay_minutes`** — 70% confidence — Statistically inferred (LLM fallback)
- **`status`** — 70% confidence — Statistically inferred (LLM fallback)
- **`gate`** — 70% confidence — Statistically inferred (LLM fallback)
- **`aircraft_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`passenger_count`** — 70% confidence — Statistically inferred (LLM fallback)
- **`timestamp`** — 70% confidence — Statistically inferred (LLM fallback)
- **`severity`** — 57% confidence — Statistically inferred (LLM fallback)
- **`crew_captain`** — 54% confidence — Statistically inferred (LLM fallback)

---

## Mixed Type Fields

- **`delay_minutes`** — Statistically inferred (LLM fallback)
- **`timestamp`** — Statistically inferred (LLM fallback)
