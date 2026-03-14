# Stream Profile Report — flights.stream

**Profiled:** 2026-03-14T11:17:09.326987+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 5

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `flight.gate_changed` | 93 | 23% | 15 | 92% | — |
| `flight.landed` | 83 | 21% | 15 | 85% | — |
| `flight.delayed` | 81 | 20% | 15 | 85% | — |
| `flight.status_changed` | 77 | 19% | 15 | 85% | — |
| `flight.departed` | 66 | 16% | 15 | 85% | — |

---

## `flight.gate_changed`

- **Events:** 93 (23% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 92%

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

## `flight.landed`

- **Events:** 83 (21% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `flight_number` | string | ✓ | 90% | — |
| `origin` | string | ✓ | 90% | — |
| `destination` | string | ✓ | 90% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 90% | — |
| `actual_departure` | timestamp_iso8601 | ○ | 80% | — |
| `delay_minutes` | integer | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `gate` | string | ○ | 70% | — |
| `aircraft_type` | string | ✓ | 90% | — |
| `passenger_count` | integer | ○ | 70% | — |
| `timestamp` | mixed | ✓ | 80% | — |
| `severity` | string | ○ | 50% | — |
| `crew_captain` | string | ○ | 40% | — |

---

## `flight.delayed`

- **Events:** 81 (20% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `flight_number` | string | ✓ | 90% | — |
| `origin` | string | ✓ | 90% | — |
| `destination` | string | ✓ | 90% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 90% | — |
| `actual_departure` | timestamp_iso8601 | ○ | 80% | — |
| `delay_minutes` | mixed | ✓ | 80% | — |
| `status` | string | ✓ | 90% | — |
| `gate` | string | ○ | 70% | — |
| `aircraft_type` | string | ✓ | 90% | — |
| `passenger_count` | integer | ○ | 80% | — |
| `timestamp` | mixed | ✓ | 80% | — |
| `severity` | string | ○ | 60% | — |
| `crew_captain` | string | ○ | 60% | — |

---

## `flight.status_changed`

- **Events:** 77 (19% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `flight_number` | string | ✓ | 90% | — |
| `origin` | string | ✓ | 90% | — |
| `destination` | string | ✓ | 90% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 90% | — |
| `actual_departure` | timestamp_iso8601 | ○ | 80% | — |
| `delay_minutes` | integer | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `gate` | string | ○ | 80% | — |
| `aircraft_type` | string | ✓ | 90% | — |
| `passenger_count` | integer | ○ | 80% | — |
| `timestamp` | mixed | ✓ | 80% | — |
| `severity` | string | ○ | 50% | — |
| `crew_captain` | string | ○ | 50% | — |

---

## `flight.departed`

- **Events:** 66 (16% of stream)
- **Top-level keys:** event_id, event_type, flight_number, origin, destination, scheduled_departure, actual_departure, delay_minutes, status, gate
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 90% | — |
| `event_type` | string | ✓ | 90% | — |
| `flight_number` | string | ✓ | 90% | — |
| `origin` | string | ✓ | 90% | — |
| `destination` | string | ✓ | 90% | — |
| `scheduled_departure` | timestamp_iso8601 | ✓ | 90% | — |
| `actual_departure` | timestamp_iso8601 | ○ | 80% | — |
| `delay_minutes` | integer | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `gate` | string | ○ | 80% | — |
| `aircraft_type` | string | ✓ | 90% | — |
| `passenger_count` | integer | ○ | 80% | — |
| `timestamp` | mixed | ✓ | 80% | — |
| `severity` | string | ○ | 70% | — |
| `crew_captain` | string | ○ | 70% | — |
