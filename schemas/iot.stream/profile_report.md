# Stream Profile Report — iot.stream

**Profiled:** 2026-03-24T13:20:26.126125+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** structural_fingerprint  
**Sub-schemas:** 3

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `struct:586e225f` | 249 | 83% | 9 | 60% | — |
| `struct:ffdb7591` | 40 | 13% | 9 | 58% | — |
| `struct:8f839e43` | 11 | 4% | 11 | 38% | — |

---

## `struct:586e225f`

- **Events:** 249 (83% of stream)
- **Top-level keys:** sensor_id, sensor_type, location, value, unit, timestamp, battery_level, signal_strength, anomaly
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `sensor_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `value` | mixed | ✓ | 70% | — |
| `unit` | string | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `battery_level` | integer | ✓ | 70% | — |
| `signal_strength` | integer | ✓ | 70% | — |
| `anomaly` | boolean | ✓ | 70% | — |

---

## `struct:ffdb7591`

- **Events:** 40 (13% of stream)
- **Top-level keys:** sensor_id, sensor_type, location, timestamp, battery_level, signal_strength, anomaly, reading
- **Confidence:** 58%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `sensor_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `battery_level` | integer | ✓ | 70% | — |
| `signal_strength` | integer | ✓ | 70% | — |
| `anomaly` | boolean | ✓ | 70% | — |
| `reading.value` | mixed | ✓ | 70% | — |
| `reading.unit` | string | ✓ | 70% | — |

---

## `struct:8f839e43`

- **Events:** 11 (4% of stream)
- **Top-level keys:** sensor_id, sensor_type, location, value, unit, timestamp, battery_level, signal_strength, anomaly, alert_level
- **Confidence:** 38%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `sensor_id` | string | ✓ | 70% | — |
| `sensor_type` | string | ✓ | 70% | — |
| `location` | string | ✓ | 70% | — |
| `value` | mixed | ✓ | 70% | — |
| `unit` | string | ✓ | 70% | — |
| `timestamp` | mixed | ✓ | 70% | — |
| `battery_level` | integer | ✓ | 70% | — |
| `signal_strength` | integer | ✓ | 70% | — |
| `anomaly` | boolean | ✓ | 70% | — |
| `alert_level` | string | ✓ | 70% | — |
| `alert_message` | string | ✓ | 70% | — |
