# Inference Report — events.iot

**Inferred:** 2026-03-24T11:29:42.257066+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Overall confidence:** 80%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 400 | 400 | 0 | 100.0% |

---

## Field Summary

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

---

## Low Confidence Fields (< 80%)

- **`battery_pct`** — 50% confidence — Battery percentage
- **`debug.rssi`** — 50% confidence — RSSI of the device
- **`debug.uptime_s`** — 50% confidence — Uptime of the device in seconds
- **`debug.free_heap`** — 50% confidence — Free heap memory
- **`motion_detected`** — 50% confidence — Whether motion was detected
- **`confidence`** — 50% confidence — Confidence level of the event
- **`zone`** — 50% confidence — Zone of the device
- **`pressure_hpa`** — 50% confidence — Pressure in hPa
- **`altitude_m`** — 50% confidence — Altitude in meters
- **`humidity_pct`** — 50% confidence — Humidity percentage
- **`dew_point_c`** — 50% confidence — Dew point in Celsius
- **`watts`** — 50% confidence — Power consumption in watts
- **`voltage`** — 50% confidence — Voltage
- **`current_amps`** — 50% confidence — Current in amps
- **`power_factor`** — 50% confidence — Power factor
- **`temperature_c`** — 50% confidence — Temperature in Celsius
- **`co2_ppm`** — 50% confidence — CO2 concentration in ppm
- **`pm25`** — 50% confidence — PM2.5 concentration
- **`pm10`** — 50% confidence — PM10 concentration
- **`tvoc_ppb`** — 50% confidence — TVOC concentration in ppb
- **`aqi`** — 50% confidence — Air quality index
- **`kwh_today`** — 50% confidence — Energy consumption in kWh today

---

## Rare Fields (< 10% presence)

- **`kwh_today`** — present in 8% of events
