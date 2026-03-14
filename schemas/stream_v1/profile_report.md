# Stream Profile Report — stream_v1

**Profiled:** 2026-03-14T11:16:21.181828+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `payment.processed` | 300 | 100% | 14 | 85% | `user.email`, `user.name`, `metadata.ip_address` |

---

## `payment.processed`

- **Events:** 300 (100% of stream)
- **Top-level keys:** event_id, event_type, timestamp, transaction_id, amount, currency, status, payment_method, user, metadata
- **Confidence:** 85%

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

**PII in this cluster:** `user.email` (email), `user.name` (name), `metadata.ip_address` (ip_address)
