# Stream Profile Report — events.iot

**Profiled:** 2026-03-19T16:04:55.567580+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** structural_fingerprint  
**Sub-schemas:** 13

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `struct:92ee5a55` | 28 | 19% | 10 | 60% | — |
| `struct:533cf3de` | 28 | 19% | 8 | 60% | — |
| `struct:086e34d2` | 26 | 17% | 8 | 60% | — |
| `struct:80db632c` | 23 | 15% | 7 | 60% | — |
| `struct:5f5c1e05` | 17 | 11% | 8 | 60% | — |
| `struct:8115fb4c` | 8 | 5% | 10 | 60% | — |
| `struct:e07a853b` | 8 | 5% | 9 | 60% | — |
| `struct:550925de` | 5 | 3% | 13 | 60% | — |
| `struct:e24e8c70` | 2 | 1% | 11 | 26% | — |
| `struct:616dc770` | 2 | 1% | 13 | 26% | — |
| `struct:82f03776` | 1 | 1% | 10 | 18% | — |
| `struct:64a644b6` | 1 | 1% | 11 | 18% | — |
| `struct:efdcacb9` | 1 | 1% | 11 | 18% | — |

---

## `struct:92ee5a55`

- **Events:** 28 (19% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, co2_ppm, pm25, pm10, tvoc_ppb, aqi
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `co2_ppm` | integer | ✓ | 70% | — |
| `pm25` | float | ✓ | 70% | — |
| `pm10` | float | ✓ | 70% | — |
| `tvoc_ppb` | integer | ✓ | 70% | — |
| `aqi` | integer | ✓ | 70% | — |

---

## `struct:533cf3de`

- **Events:** 28 (19% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, temperature_c, temperature_f, battery_pct
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `temperature_c` | mixed | ✓ | 70% | — |
| `temperature_f` | float | ✓ | 70% | — |
| `battery_pct` | integer | ✓ | 70% | — |

---

## `struct:086e34d2`

- **Events:** 26 (17% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, humidity_pct, dew_point_c, battery_pct
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `humidity_pct` | float | ✓ | 70% | — |
| `dew_point_c` | float | ✓ | 70% | — |
| `battery_pct` | integer | ✓ | 70% | — |

---

## `struct:80db632c`

- **Events:** 23 (15% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, pressure_hpa, altitude_m
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `pressure_hpa` | float | ✓ | 70% | — |
| `altitude_m` | float | ✓ | 70% | — |

---

## `struct:5f5c1e05`

- **Events:** 17 (11% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, motion_detected, confidence, zone
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `motion_detected` | boolean | ✓ | 70% | — |
| `confidence` | float | ✓ | 70% | — |
| `zone` | string | ✓ | 70% | — |

---

## `struct:8115fb4c`

- **Events:** 8 (5% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, watts, voltage, current_amps, power_factor, kwh_today
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `watts` | float | ✓ | 70% | — |
| `voltage` | float | ✓ | 70% | — |
| `current_amps` | float | ✓ | 70% | — |
| `power_factor` | float | ✓ | 70% | — |
| `kwh_today` | float | ✓ | 70% | — |

---

## `struct:e07a853b`

- **Events:** 8 (5% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, watts, voltage, current_amps, power_factor
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `watts` | float | ✓ | 70% | — |
| `voltage` | float | ✓ | 70% | — |
| `current_amps` | float | ✓ | 70% | — |
| `power_factor` | float | ✓ | 70% | — |

---

## `struct:550925de`

- **Events:** 5 (3% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, co2_ppm, pm25, pm10, tvoc_ppb, aqi
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `co2_ppm` | integer | ✓ | 70% | — |
| `pm25` | float | ✓ | 70% | — |
| `pm10` | float | ✓ | 70% | — |
| `tvoc_ppb` | integer | ✓ | 70% | — |
| `aqi` | integer | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |

---

## `struct:e24e8c70`

- **Events:** 2 (1% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, temperature_c, temperature_f, battery_pct, debug
- **Confidence:** 26%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `temperature_c` | float | ✓ | 70% | — |
| `temperature_f` | float | ✓ | 70% | — |
| `battery_pct` | integer | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |

---

## `struct:616dc770`

- **Events:** 2 (1% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, watts, voltage, current_amps, power_factor, kwh_today
- **Confidence:** 26%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `watts` | float | ✓ | 70% | — |
| `voltage` | float | ✓ | 70% | — |
| `current_amps` | float | ✓ | 70% | — |
| `power_factor` | float | ✓ | 70% | — |
| `kwh_today` | float | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |

---

## `struct:82f03776`

- **Events:** 1 (1% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, pressure_hpa, altitude_m, debug
- **Confidence:** 18%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `pressure_hpa` | float | ✓ | 70% | — |
| `altitude_m` | null | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |

---

## `struct:64a644b6`

- **Events:** 1 (1% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, motion_detected, confidence, zone, debug
- **Confidence:** 18%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `motion_detected` | boolean | ✓ | 70% | — |
| `confidence` | null | ✓ | 70% | — |
| `zone` | string | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |

---

## `struct:efdcacb9`

- **Events:** 1 (1% of stream)
- **Top-level keys:** device_id, sensor_type, location, firmware, timestamp, humidity_pct, dew_point_c, battery_pct, debug
- **Confidence:** 18%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `device_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `firmware` | string | ✓ | 70% | — |
| `timestamp` | string | ✓ | 70% | — |
| `humidity_pct` | float | ✓ | 70% | — |
| `dew_point_c` | float | ✓ | 70% | — |
| `battery_pct` | integer | ✓ | 70% | — |
| `debug.rssi` | integer | ✓ | 70% | — |
| `debug.uptime_s` | integer | ✓ | 70% | — |
| `debug.free_heap` | integer | ✓ | 70% | — |
