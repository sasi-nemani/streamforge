# Inference Report — events.iot

**Inferred:** 2026-03-19T16:04:55.567580+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Overall confidence:** 60%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 150 | 150 | 0 | 100.0% |

---

## Field Summary

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

## Low Confidence Fields (< 80%)

- **`device_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`sensor_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`location`** — 70% confidence — Statistically inferred (LLM fallback)
- **`firmware`** — 70% confidence — Statistically inferred (LLM fallback)
- **`timestamp`** — 70% confidence — Statistically inferred (LLM fallback)
- **`co2_ppm`** — 70% confidence — Statistically inferred (LLM fallback)
- **`pm25`** — 70% confidence — Statistically inferred (LLM fallback)
- **`pm10`** — 70% confidence — Statistically inferred (LLM fallback)
- **`tvoc_ppb`** — 70% confidence — Statistically inferred (LLM fallback)
- **`aqi`** — 70% confidence — Statistically inferred (LLM fallback)
