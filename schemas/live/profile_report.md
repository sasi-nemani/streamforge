# Stream Profile Report — live

**Profiled:** 2026-03-14T10:57:42.398734+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 200  
**Parse success rate:** 100.0%  
**Discovery method:** single  
**Sub-schemas:** 1

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `wiki_edit` | 200 | 100% | 16 | 90% | — |

---

## `wiki_edit`

- **Events:** 200 (100% of stream)
- **Top-level keys:** event_type, wiki, server_name, title, namespace, change_type, user, bot, minor, comment
- **Confidence:** 90%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `event_type` | string | ✓ | 100% | — |
| `wiki` | string | ✓ | 100% | — |
| `server_name` | string | ✓ | 100% | — |
| `title` | string | ✓ | 100% | — |
| `namespace` | integer | ✓ | 100% | — |
| `change_type` | string | ✓ | 100% | — |
| `user` | string | ✓ | 100% | — |
| `bot` | boolean | ✓ | 100% | — |
| `minor` | boolean | ✓ | 100% | — |
| `comment` | string | ✓ | 100% | — |
| `length_old` | integer | ○ | 80% | — |
| `length_new` | integer | ○ | 80% | — |
| `revision_old` | integer | ○ | 80% | — |
| `revision_new` | integer | ○ | 80% | — |
| `timestamp` | timestamp_epoch_ms | ✓ | 100% | — |
| `ingested_at` | timestamp_iso8601 | ✓ | 100% | — |
