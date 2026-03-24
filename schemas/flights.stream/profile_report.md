# Stream Profile Report — flights.stream

**Profiled:** 2026-03-24T13:49:53.183684+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 5

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `flight.gate_changed` | 70 | 23% | 15 | 85% | — |
| `flight.landed` | 69 | 23% | 15 | 85% | — |
| `flight.delayed` | 58 | 19% | 15 | 60% | — |
| `flight.status_changed` | 53 | 18% | 15 | 60% | — |
| `flight.departed` | 50 | 17% | 15 | 60% | — |

---

## `flight.gate_changed`

- **Events:** 70 (23% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

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

## `flight.landed`

- **Events:** 69 (23% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

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
| `timestamp` | timestamp_iso8601 | ✓ | 99% | — |
| `severity` | string | ✓ | 80% | — |
| `crew_captain` | string | ✓ | 80% | — |

---

## `flight.delayed`

- **Events:** 58 (19% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `flight_number` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `actual_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `delay_minutes` | mixed | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `gate` | string | ✓ | 70% | — |
| `aircraft_type` | string | ✓ | 70% | — |
| `passenger_count` | integer | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `severity` | string | ○ | 56% | — |
| `crew_captain` | string | ○ | 56% | — |

---

## `flight.status_changed`

- **Events:** 53 (18% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `flight_number` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `actual_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `delay_minutes` | mixed | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `gate` | string | ✓ | 70% | — |
| `aircraft_type` | string | ✓ | 70% | — |
| `passenger_count` | integer | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `crew_captain` | string | ○ | 55% | — |
| `severity` | string | ○ | 57% | — |

---

## `flight.departed`

- **Events:** 50 (17% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 70% | — |
| `flight_number` | string | ✓ | 70% | — |
| `origin` | string | ✓ | 70% | — |
| `destination` | string | ✓ | 70% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `actual_departure` | timestamp_iso8601 | ✓ | 99% | — |
| `delay_minutes` | mixed | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `gate` | string | ✓ | 70% | — |
| `aircraft_type` | string | ✓ | 70% | — |
| `passenger_count` | integer | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `severity` | string | ○ | 56% | — |
| `crew_captain` | string | ○ | 55% | — |
