# Inference Report — events.payments

**Inferred:** 2026-03-19T16:04:45.710762+00:00  
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
| `event_id` | string | ✓ | 70% | — |
| `event_type` | string | ✓ | 70% | — |
| `user_id` | string | ✓ | 70% | — |
| `merchant` | string | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `status` | string | ✓ | 70% | — |
| `amount` | float | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user_email` | string | ○ | 65% | email |

---

## PII Fields

- **`user_email`** — email

---

## Low Confidence Fields (< 80%)

- **`event_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`event_type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`user_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`merchant`** — 70% confidence — Statistically inferred (LLM fallback)
- **`currency`** — 70% confidence — Statistically inferred (LLM fallback)
- **`status`** — 70% confidence — Statistically inferred (LLM fallback)
- **`amount`** — 70% confidence — Statistically inferred (LLM fallback)
- **`timestamp`** — 70% confidence — Statistically inferred (LLM fallback)
- **`user_email`** — 65% confidence — Statistically inferred (LLM fallback)
