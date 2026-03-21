# Stream Profile Report — events.payments

**Profiled:** 2026-03-19T16:04:45.710762+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 4

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `payment.failed` | 52 | 35% | 9 | 60% | `user_email` |
| `payment.created` | 49 | 33% | 9 | 60% | `user_email` |
| `payment.updated` | 48 | 32% | 9 | 60% | `user_email` |
| `payment` | 1 | 1% | 4 | 18% | — |

---

## `payment.failed`

- **Events:** 52 (35% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 60%

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

**PII in this cluster:** `user_email` (email)

---

## `payment.created`

- **Events:** 49 (33% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 60%

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
| `user_email` | string | ○ | 62% | email |

**PII in this cluster:** `user_email` (email)

---

## `payment.updated`

- **Events:** 48 (32% of stream)
- **Top-level keys:** event_id, event_type, user_id, merchant, currency, status, amount, timestamp, user_email
- **Confidence:** 60%

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
| `user_email` | string | ○ | 63% | email |

**PII in this cluster:** `user_email` (email)

---

## `payment`

- **Events:** 1 (1% of stream)
- **Top-level keys:** event_type, amount, currency, user_id
- **Confidence:** 18%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 70% | — |
| `amount` | float | ✓ | 70% | — |
| `currency` | string | ✓ | 70% | — |
| `user_id` | string | ✓ | 70% | — |
