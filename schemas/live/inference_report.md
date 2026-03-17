# Inference Report — live

**Inferred:** 2026-03-14T10:57:42.398734+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 200  
**Overall confidence:** 90%

---

## Field Summary

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
