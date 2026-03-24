# Stream Profile Report — events.payments

**Profiled:** 2026-03-24T11:29:57.838393+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 3

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `payment.updated` | 148 | 37% | 9 | 85% | `user_email` |
| `payment.created` | 128 | 32% | 9 | 85% | `user_email` |
| `payment.failed` | 124 | 31% | 9 | 85% | `user_email` |

---

## `payment.updated`

- **Events:** 148 (37% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 85%

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

**PII in this cluster:** `user_email` (email)

---

## `payment.created`

- **Events:** 128 (32% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 85%

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

**PII in this cluster:** `user_email` (email)

---

## `payment.failed`

- **Events:** 124 (31% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 85%

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

**PII in this cluster:** `user_email` (email)
