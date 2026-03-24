# Inference Report — flights.stream

**Inferred:** 2026-03-24T13:49:53.183684+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 85%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 400 | 400 | 0 | 100.0% |

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 90% | — |
| `flight_number` | string | ✓ | 90% | — |
| `origin` | string | ✓ | 90% | — |
| `destination` | string | ✓ | 90% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `actual_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `delay_minutes` | integer | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `gate` | string | ✓ | 90% | — |
| `aircraft_type` | string | ✓ | 90% | — |
| `passenger_count` | integer | ✓ | 90% | — |
| `timestamp` | mixed | ✓ | 90% | — |
| `severity` | string | ✓ | 90% | — |
| `crew_captain` | string | ✓ | 90% | — |

---

## Mixed Type Fields

- **`timestamp`** — Timestamp in Unix epoch ms, ISO8601 string, or RFC2822 string
