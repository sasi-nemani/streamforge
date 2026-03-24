# Stream Profile Report — stream_v1

**Profiled:** 2026-03-24T13:06:42.073554+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 300  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `payment.processed` | 300 | 100% | 13 | 95% | `user.email`, `user.name`, `metadata.ip_address` |

---

## `payment.processed`

- **Events:** 300 (100% of stream)
- **Top-level keys:** event_id, event_type, timestamp, transaction_id, amount, currency, status, payment_method, user, metadata
- **Confidence:** 95%

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

**PII in this cluster:** `user.email` (email), `user.name` (name), `metadata.ip_address` (ip_address)
