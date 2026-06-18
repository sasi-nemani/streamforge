# Stream Profile Report — stream_v1

**Profiled:** 2026-06-18T15:25:01.087034+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `payment.processed` | 300 | 100% | 16 | 68% | `user.email`, `user.name`, `metadata.ip_address` |

---

## `payment.processed`

- **Events:** 300 (100% of stream)
- **Top-level keys:** event_id, event_type, timestamp, transaction_id, amount, currency, status, payment_method, user, metadata
- **Confidence:** 68%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_id` | uuid | ✓ | 100% | — |
| `event_type` | string | ✓ | 100% | — |
| `timestamp` | timestamp_epoch_ms | ✓ | 100% | — |
| `transaction_id` | string | ✓ | 100% | — |
| `amount` | mixed | ✓ | 100% | — |
| `currency` | string | ✓ | 100% | — |
| `status` | string | ✓ | 100% | — |
| `payment_method` | string | ✓ | 100% | — |
| `user.user_id` | string | ✓ | 100% | — |
| `user.email` | email | ✓ | 100% | email |
| `user.name` | string | ✓ | 100% | name |
| `metadata.ip_address` | string | ✓ | 100% | ip_address |
| `metadata.user_agent` | string | ✓ | 100% | — |
| `metadata.region` | string | ✓ | 100% | — |
| `user_id` | string | ○ | 100% | — |
| `user_email` | email | ○ | 100% | email |

**PII in this cluster:** `user.email` (email), `user.name` (name), `metadata.ip_address` (ip_address), `user_email` (email)
