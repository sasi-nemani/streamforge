# Stream Profile Report — flights.stream

**Profiled:** 2026-03-24T13:49:00.389963+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 5

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `flight.gate_changed` | 70 | 23% | 15 | 60% | — |
| `flight.delayed` | 64 | 21% | 15 | 85% | — |
| `flight.status_changed` | 59 | 20% | 15 | 85% | — |
| `flight.landed` | 58 | 19% | 15 | 85% | — |
| `flight.departed` | 49 | 16% | 15 | 64% | — |

---

## `flight.gate_changed`

- **Events:** 70 (23% of stream)
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
| `crew_captain` | string | ○ | 53% | — |
| `severity` | string | ○ | 57% | — |

---

## `flight.delayed`

- **Events:** 64 (21% of stream)
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
| `timestamp` | timestamp_iso8601 | ✓ | 90% | — |
| `severity` | string | ✓ | 80% | — |
| `crew_captain` | string | ✓ | 80% | — |

---

## `flight.status_changed`

- **Events:** 59 (20% of stream)
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

- **Events:** 58 (19% of stream)
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

## `flight.departed`

- **Events:** 49 (16% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 64%

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
| `crew_captain` | string | ○ | 54% | — |
| `severity` | string | ○ | 56% | — |
