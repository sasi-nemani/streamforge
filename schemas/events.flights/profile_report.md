# Stream Profile Report — events.flights

**Profiled:** 2026-03-19T16:04:59.671314+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `struct:ce4f0e0f` | 150 | 100% | 17 | 60% | — |

---

## `struct:ce4f0e0f`

- **Events:** 150 (100% of stream)
- **Top-level keys:** icao24, callsign, origin_country, time_position, last_contact, longitude, latitude, baro_altitude, on_ground, velocity
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `icao24` | string | ✓ | 70% | — |
| `callsign` | string | ✓ | 70% | — |
| `origin_country` | string | ✓ | 70% | — |
| `time_position` | integer | ✓ | 70% | — |
| `last_contact` | integer | ✓ | 70% | — |
| `longitude` | float | ✓ | 70% | — |
| `latitude` | float | ✓ | 70% | — |
| `baro_altitude` | mixed | ✓ | 70% | — |
| `on_ground` | boolean | ✓ | 70% | — |
| `velocity` | mixed | ✓ | 70% | — |
| `true_track` | mixed | ✓ | 70% | — |
| `vertical_rate` | mixed | ✓ | 70% | — |
| `sensors` | null | ✓ | 70% | — |
| `geo_altitude` | mixed | ✓ | 70% | — |
| `squawk` | string | ✓ | 70% | — |
| `spi` | boolean | ✓ | 70% | — |
| `position_source` | integer | ✓ | 70% | — |
