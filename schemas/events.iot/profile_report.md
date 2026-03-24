# Stream Profile Report — events.iot

**Profiled:** 2026-03-24T11:29:42.257066+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `iot_sensor` | 400 | 100% | 28 | 80% | — |

---

## `iot_sensor`

- **Events:** 400 (100% of stream)
- **Top-level keys:** event_type, device_id, sensor_type, location, firmware, timestamp, battery_pct, debug, motion_detected, confidence
- **Confidence:** 80%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 100% | — |
| `device_id` | string | ✓ | 100% | — |
| `sensor_type` | string | ✓ | 100% | — |
| `location` | string | ✓ | 100% | — |
| `firmware` | string | ✓ | 100% | — |
| `timestamp` | timestamp_iso8601 | ✓ | 100% | — |
| `battery_pct` | integer | ○ | 50% | — |
| `debug.rssi` | integer | ○ | 50% | — |
| `debug.uptime_s` | integer | ○ | 50% | — |
| `debug.free_heap` | integer | ○ | 50% | — |
| `motion_detected` | boolean | ○ | 50% | — |
| `confidence` | float | ○ | 50% | — |
| `zone` | string | ○ | 50% | — |
| `pressure_hpa` | float | ○ | 50% | — |
| `altitude_m` | float | ○ | 50% | — |
| `humidity_pct` | float | ○ | 50% | — |
| `dew_point_c` | float | ○ | 50% | — |
| `watts` | float | ○ | 50% | — |
| `voltage` | float | ○ | 50% | — |
| `current_amps` | float | ○ | 50% | — |
| `power_factor` | float | ○ | 50% | — |
| `temperature_c` | float | ○ | 50% | — |
| `co2_ppm` | integer | ○ | 50% | — |
| `pm25` | float | ○ | 50% | — |
| `pm10` | float | ○ | 50% | — |
| `tvoc_ppb` | integer | ○ | 50% | — |
| `aqi` | integer | ○ | 50% | — |
| `kwh_today` | float | ○ | 50% | — |
