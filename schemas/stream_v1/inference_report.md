# Inference Report — stream_v1

**Inferred:** 2026-03-24T13:06:42.073554+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 95%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 300 | 300 | 0 | 100.0% |

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 99% | — |
| `event_type` | string | ✓ | 99% | — |
| `transaction_id` | string | ✓ | 99% | — |
| `amount` | float | ✓ | 99% | — |
| `currency` | string | ✓ | 99% | — |
| `status` | string | ✓ | 99% | — |
| `payment_method` | string | ✓ | 99% | — |
| `user.user_id` | string | ✓ | 99% | — |
| `user.email` | email | ✓ | 99% | email |
| `user.name` | string | ✓ | 99% | name |
| `metadata.ip_address` | string | ✓ | 99% | ip_address |
| `metadata.user_agent` | string | ✓ | 99% | — |
| `metadata.region` | string | ✓ | 99% | — |

---

## PII Fields

- **`user.email`** — email
- **`user.name`** — name
- **`metadata.ip_address`** — ip_address
