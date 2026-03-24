# Inference Report — events.all

**Inferred:** 2026-03-22T16:37:14.277783+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 85%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 300 | 300 | 0 | 100.0% |

---

## Field Summary

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

## Low Confidence Fields (< 80%)

- **`debug.rssi`** — 70% confidence — RSSI value
- **`debug.uptime_s`** — 70% confidence — Uptime in seconds
- **`debug.free_heap`** — 70% confidence — Free heap size in bytes
- **`watts`** — 70% confidence — Power consumption in watts
- **`voltage`** — 70% confidence — Voltage in volts
- **`current_amps`** — 70% confidence — Current in amperes
- **`power_factor`** — 70% confidence — Power factor
- **`motion_detected`** — 70% confidence — Motion detected
- **`confidence`** — 70% confidence — Confidence level
- **`zone`** — 70% confidence — Zone identifier
- **`humidity_pct`** — 60% confidence — Humidity percentage
- **`dew_point_c`** — 60% confidence — Dew point temperature in Celsius
- **`co2_ppm`** — 60% confidence — CO2 concentration in ppm
- **`pm25`** — 60% confidence — PM2.5 concentration in μg/m³
- **`pm10`** — 60% confidence — PM10 concentration in μg/m³
- **`tvoc_ppb`** — 60% confidence — TVOC concentration in ppb
- **`aqi`** — 60% confidence — Air quality index
- **`kwh_today`** — 50% confidence — Energy consumption in kWh
- **`pressure_hpa`** — 50% confidence — Pressure in hPa
- **`altitude_m`** — 50% confidence — Altitude in meters

---

## Rare Fields (< 10% presence)

- **`pressure_hpa`** — present in 9% of events
- **`altitude_m`** — present in 9% of events
