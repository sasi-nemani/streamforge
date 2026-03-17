# Inference Report — stream_v1

**Inferred:** 2026-03-14T11:16:21.181828+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Overall confidence:** 85%

---

## Field Summary

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 95% | — |
| `event_type` | string | ✓ | 95% | — |
| `timestamp` | timestamp_epoch_ms | ✓ | 95% | — |
| `transaction_id` | string | ✓ | 95% | — |
| `amount` | mixed | ✓ | 80% | — |
| `currency` | string | ✓ | 90% | — |
| `status` | string | ✓ | 90% | — |
| `payment_method` | string | ✓ | 90% | — |
| `user.user_id` | string | ○ | 80% | — |
| `user.email` | email | ○ | 80% | email |
| `user.name` | string | ○ | 80% | name |
| `metadata.ip_address` | string | ○ | 70% | ip_address |
| `metadata.user_agent` | string | ○ | 70% | — |
| `metadata.region` | string | ○ | 70% | — |

---

## PII Fields

- **`user.email`** — email
- **`user.name`** — name
- **`metadata.ip_address`** — ip_address

---

## Low Confidence Fields (< 80%)

- **`metadata.ip_address`** — 70% confidence — IP address of the user
- **`metadata.user_agent`** — 70% confidence — User agent of the user
- **`metadata.region`** — 70% confidence — Region of the user

---

## Mixed Type Fields

- **`amount`** — Transaction amount, sometimes string and sometimes number
