# Inference Report — events.flights

**Inferred:** 2026-03-19T16:04:59.671314+00:00  
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

---

## Low Confidence Fields (< 80%)

- **`icao24`** — 70% confidence — Statistically inferred (LLM fallback)
- **`callsign`** — 70% confidence — Statistically inferred (LLM fallback)
- **`origin_country`** — 70% confidence — Statistically inferred (LLM fallback)
- **`time_position`** — 70% confidence — Statistically inferred (LLM fallback)
- **`last_contact`** — 70% confidence — Statistically inferred (LLM fallback)
- **`longitude`** — 70% confidence — Statistically inferred (LLM fallback)
- **`latitude`** — 70% confidence — Statistically inferred (LLM fallback)
- **`baro_altitude`** — 70% confidence — Statistically inferred (LLM fallback)
- **`on_ground`** — 70% confidence — Statistically inferred (LLM fallback)
- **`velocity`** — 70% confidence — Statistically inferred (LLM fallback)
- **`true_track`** — 70% confidence — Statistically inferred (LLM fallback)
- **`vertical_rate`** — 70% confidence — Statistically inferred (LLM fallback)
- **`sensors`** — 70% confidence — Statistically inferred (LLM fallback)
- **`geo_altitude`** — 70% confidence — Statistically inferred (LLM fallback)
- **`squawk`** — 70% confidence — Statistically inferred (LLM fallback)
- **`spi`** — 70% confidence — Statistically inferred (LLM fallback)
- **`position_source`** — 70% confidence — Statistically inferred (LLM fallback)

---

## Mixed Type Fields

- **`baro_altitude`** — Statistically inferred (LLM fallback)
- **`velocity`** — Statistically inferred (LLM fallback)
- **`true_track`** — Statistically inferred (LLM fallback)
- **`vertical_rate`** — Statistically inferred (LLM fallback)
- **`geo_altitude`** — Statistically inferred (LLM fallback)
