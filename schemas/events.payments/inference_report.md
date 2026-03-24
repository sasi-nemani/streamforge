# Inference Report — events.payments

**Inferred:** 2026-03-24T11:29:57.838393+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Overall confidence:** 85%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 400 | 400 | 0 | 100.0% |

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 90% | — |
| `user_id` | string | ✓ | 90% | — |
| `merchant` | string | ✓ | 90% | — |
| `currency` | string | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `amount` | float | ✓ | 90% | — |
| `timestamp` | timestamp_epoch_ms | ✓ | 99% | — |
| `user_email` | email | ○ | 97% | email |

---

## PII Fields

- **`user_email`** — email
