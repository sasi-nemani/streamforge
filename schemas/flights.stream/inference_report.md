# Inference Report — flights.stream

**Inferred:** 2026-03-14T11:17:09.326987+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Overall confidence:** 92%

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 100% | — |
| `event_type` | string | ✓ | 100% | — |
| `flight_number` | string | ✓ | 100% | — |
| `origin` | string | ✓ | 100% | — |
| `destination` | string | ✓ | 100% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 100% | — |
| `actual_departure` | timestamp_iso8601 | ○ | 90% | — |
| `delay_minutes` | integer | ✓ | 100% | — |
| `status` | string | ✓ | 100% | — |
| `gate` | string | ○ | 90% | — |
| `aircraft_type` | string | ✓ | 100% | — |
| `passenger_count` | integer | ○ | 90% | — |
| `timestamp` | mixed | ✓ | 95% | — |
| `severity` | string | ○ | 50% | — |
| `crew_captain` | string | ○ | 20% | — |

---

## Low Confidence Fields (< 80%)

- **`severity`** — 50% confidence — Severity level, e.g. 'INFO', 'CRITICAL', 'WARNING', may be null if not available
- **`crew_captain`** — 20% confidence — Crew captain name, may be null if not available

---

## Mixed Type Fields

- **`timestamp`** — Timestamp, either in Unix epoch milliseconds or ISO 8601 format
