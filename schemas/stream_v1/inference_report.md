# Inference Report — stream_v1

**Inferred:** 2026-03-14T09:59:39.642605+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 95%

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 100% | — |
| `event_type` | string | ✓ | 100% | — |
| `timestamp` | timestamp_epoch_ms | ✓ | 100% | — |
| `transaction_id` | string | ✓ | 100% | — |
| `amount` | float | ✓ | 100% | — |
| `currency` | string | ✓ | 100% | — |
| `status` | string | ✓ | 100% | — |
| `payment_method` | string | ✓ | 100% | — |
| `user.user_id` | string | ○ | 96% | — |
| `user.email` | email | ○ | 96% | email |
| `user.name` | string | ○ | 96% | name |
| `metadata.ip_address` | string | ○ | 90% | ip_address |
| `metadata.user_agent` | string | ○ | 90% | — |
| `metadata.region` | string | ○ | 90% | — |
| `user_id` | string | ○ | 4% | — |
| `user_email` | email | ○ | 4% | email |

---

## PII Fields

- **`user.email`** — email
- **`user.name`** — name
- **`metadata.ip_address`** — ip_address
- **`user_email`** — email

---

## Low Confidence Fields (< 80%)

- **`user_id`** — 4% confidence — Unique identifier for the user (duplicate field)
- **`user_email`** — 4% confidence — Email address of the user (duplicate field)

---

## Rare Fields (< 10% presence)

- **`user_id`** — present in 4% of events
- **`user_email`** — present in 4% of events
