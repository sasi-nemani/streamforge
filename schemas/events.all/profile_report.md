# Stream Profile Report — events.all

**Profiled:** 2026-03-22T16:37:14.277783+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 7

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `iot_sensor` | 100 | 33% | 28 | 85% | — |
| `booking.updated` | 44 | 15% | 19 | 61% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `payment.created` | 39 | 13% | 9 | 57% | `user_email` |
| `payment.failed` | 32 | 11% | 9 | 52% | `user_email` |
| `payment.updated` | 29 | 10% | 9 | 50% | `user_email` |
| `booking.cancelled` | 28 | 9% | 19 | 50% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |
| `booking.created` | 28 | 9% | 19 | 50% | `passengers[].passenger_name`, `passengers[].ticket_number`, `passengers[].passport_number` |

---

## `iot_sensor`

- **Events:** 100 (33% of stream)
- **Top-level keys:** event_type, device_id, sensor_type, location, firmware, timestamp, battery_pct, temperature_c, debug, watts
- **Confidence:** 85%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 90% | — |
| `device_id` | string | ✓ | 90% | — |
| `sensor_type` | string | ✓ | 90% | — |
| `location` | string | ✓ | 90% | — |
| `firmware` | string | ✓ | 90% | — |
| `timestamp` | timestamp_iso8601 | ✓ | 99% | — |
| `battery_pct` | integer | ✓ | 80% | — |
| `temperature_c` | float | ✓ | 80% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |
| `watts` | float | ✓ | 70% | — |
| `voltage` | float | ✓ | 70% | — |
| `current_amps` | float | ✓ | 70% | — |
| `power_factor` | float | ✓ | 70% | — |
| `motion_detected` | boolean | ✓ | 70% | — |
| `confidence` | float | ✓ | 70% | — |
| `zone` | string | ✓ | 70% | — |
| `humidity_pct` | float | ✓ | 60% | — |
| `dew_point_c` | float | ✓ | 60% | — |
| `co2_ppm` | integer | ✓ | 60% | — |
| `pm25` | float | ✓ | 60% | — |
| `pm10` | float | ✓ | 60% | — |
| `tvoc_ppb` | integer | ✓ | 60% | — |
| `aqi` | integer | ✓ | 60% | — |
| `kwh_today` | float | ✓ | 50% | — |
| `pressure_hpa` | float | ✓ | 50% | — |
| `altitude_m` | float | ✓ | 50% | — |

---

## `booking.updated`

- **Events:** 44 (15% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 61%

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
| `passengers[].passport_number` | string | ○ | 64% | passport |
| `passengers[].date_of_birth` | string | ○ | 59% | phone, date_of_birth |
| `baggage_allowance_kg` | integer | ○ | 56% | — |
| `passengers[].frequent_flyer_number` | string | ○ | 61% | loyalty_number |
| `contact_phone` | string | ○ | 60% | phone |
| `contact_email` | string | ○ | 60% | email |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].date_of_birth` (phone, date_of_birth), `passengers[].frequent_flyer_number` (loyalty_number), `contact_phone` (phone), `contact_email` (email)

---

## `payment.created`

- **Events:** 39 (13% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 57%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `user_id` | string | ✓ | 70% | — |
| `merchant` | string | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `amount` | float | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user_email` | string | ✓ | 70% | email |

**PII in this cluster:** `user_email` (email)

---

## `payment.failed`

- **Events:** 32 (11% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 52%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `user_id` | string | ✓ | 70% | — |
| `merchant` | string | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `amount` | float | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user_email` | string | ✓ | 70% | email |

**PII in this cluster:** `user_email` (email)

---

## `payment.updated`

- **Events:** 29 (10% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 50%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `user_id` | string | ✓ | 70% | — |
| `merchant` | string | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `amount` | float | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user_email` | string | ✓ | 70% | email |

**PII in this cluster:** `user_email` (email)

---

## `booking.cancelled`

- **Events:** 28 (9% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 50%

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
| `passengers[].passport_number` | string | ○ | 64% | passport |
| `passengers[].frequent_flyer_number` | string | ○ | 62% | loyalty_number |
| `contact_email` | string | ○ | 63% | email |
| `contact_phone` | string | ○ | 59% | phone |
| `passengers[].date_of_birth` | string | ○ | 61% | phone, date_of_birth |
| `baggage_allowance_kg` | integer | ○ | 56% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `passengers[].frequent_flyer_number` (loyalty_number), `contact_email` (email), `contact_phone` (phone), `passengers[].date_of_birth` (phone, date_of_birth)

---

## `booking.created`

- **Events:** 28 (9% of stream)
- **Top-level keys:** booking_ref, event_type, airline, origin, destination, cabin, status, total_price, currency, created_at
- **Confidence:** 50%

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
| `passengers[].passport_number` | string | ○ | 62% | passport |
| `contact_email` | string | ○ | 59% | email |
| `contact_phone` | string | ○ | 61% | phone |
| `passengers[].frequent_flyer_number` | string | ○ | 61% | loyalty_number |
| `passengers[].date_of_birth` | string | ○ | 60% | phone, date_of_birth |
| `baggage_allowance_kg` | integer | ○ | 53% | — |

**PII in this cluster:** `passengers[].passenger_name` (name), `passengers[].ticket_number` (passport), `passengers[].passport_number` (passport), `contact_email` (email), `contact_phone` (phone), `passengers[].frequent_flyer_number` (loyalty_number), `passengers[].date_of_birth` (phone, date_of_birth)
