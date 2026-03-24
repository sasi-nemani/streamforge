# Inference Report — events.wiki

**Inferred:** 2026-03-24T11:30:15.813210+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 400  
**Overall confidence:** 95%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 400 | 400 | 0 | 100.0% |

---

## Field Summary

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

---

## PII Fields

- **`title`** — card_number
- **`comment`** — card_number
