# Inference Report — iot.stream

**Inferred:** 2026-03-24T13:20:26.126125+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 60%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 500 | 500 | 0 | 100.0% |

---

## Field Summary

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

## Low Confidence Fields (< 80%)

- **`sensor_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`sensor_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`location`** — 70% confidence — Statistically inferred (LLM fallback)
- **`value`** — 70% confidence — Statistically inferred (LLM fallback)
- **`unit`** — 70% confidence — Statistically inferred (LLM fallback)
- **`timestamp`** — 70% confidence — Statistically inferred (LLM fallback)
- **`battery_level`** — 70% confidence — Statistically inferred (LLM fallback)
- **`signal_strength`** — 70% confidence — Statistically inferred (LLM fallback)
- **`anomaly`** — 70% confidence — Statistically inferred (LLM fallback)

---

## Mixed Type Fields

- **`value`** — Statistically inferred (LLM fallback)
- **`timestamp`** — Statistically inferred (LLM fallback)
