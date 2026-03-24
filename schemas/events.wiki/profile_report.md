# Stream Profile Report — events.wiki

**Profiled:** 2026-03-24T11:30:15.813210+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 2

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `edit` | 347 | 87% | 16 | 95% | `title`, `comment` |
| `new` | 53 | 13% | 16 | 95% | — |

---

## `edit`

- **Events:** 347 (87% of stream)
- **Top-level keys:** event_type, wiki, type, namespace, title, title_url, comment, user, bot, minor
- **Confidence:** 95%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 100% | — |
| `wiki` | string | ✓ | 100% | — |
| `type` | string | ✓ | 100% | — |
| `namespace` | integer | ✓ | 100% | — |
| `title` | string | ✓ | 100% | card_number |
| `title_url` | string | ✓ | 100% | — |
| `comment` | string | ✓ | 100% | card_number |
| `user` | string | ✓ | 100% | — |
| `bot` | boolean | ✓ | 100% | — |
| `minor` | boolean | ✓ | 100% | — |
| `old_length` | integer | ✓ | 100% | — |
| `new_length` | integer | ✓ | 100% | — |
| `length_delta` | integer | ✓ | 100% | — |
| `revision_id` | integer | ✓ | 100% | — |
| `parent_revision_id` | integer | ✓ | 100% | — |
| `timestamp` | timestamp_iso8601 | ✓ | 100% | — |

**PII in this cluster:** `title` (card_number), `comment` (card_number)

---

## `new`

- **Events:** 53 (13% of stream)
- **Top-level keys:** event_type, wiki, type, namespace, title, title_url, comment, user, bot, minor
- **Confidence:** 95%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 100% | — |
| `wiki` | string | ✓ | 100% | — |
| `type` | string | ✓ | 100% | — |
| `namespace` | integer | ✓ | 100% | — |
| `title` | string | ✓ | 100% | — |
| `title_url` | string | ✓ | 100% | — |
| `comment` | string | ✓ | 100% | — |
| `user` | string | ✓ | 100% | — |
| `bot` | boolean | ✓ | 100% | — |
| `minor` | boolean | ✓ | 100% | — |
| `old_length` | integer | ✓ | 100% | — |
| `new_length` | integer | ✓ | 100% | — |
| `length_delta` | integer | ✓ | 100% | — |
| `revision_id` | integer | ✓ | 100% | — |
| `parent_revision_id` | integer | ✓ | 100% | — |
| `timestamp` | timestamp_iso8601 | ✓ | 100% | — |
