# Stream Profile Report — events.wikipedia

**Profiled:** 2026-03-19T16:05:09.595843+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 4

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `edit` | 73 | 49% | 30 | 60% | `meta.uri`, `title`, `title_url` |
| `categorize` | 57 | 38% | 24 | 60% | — |
| `log` | 11 | 7% | 35 | 60% | `meta.uri`, `title`, `title_url` |
| `new` | 9 | 6% | 28 | 60% | `meta.uri`, `title`, `title_url` |

---

## `edit`

- **Events:** 73 (49% of stream)
- **Top-level keys:** meta, id, type, namespace, title, title_url, comment, timestamp, user, bot
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `meta.uri` | string | ✓ | 70% | passport |
| `meta.request_id` | string | ✓ | 70% | — |
| `meta.id` | string | ✓ | 70% | — |
| `meta.domain` | string | ✓ | 70% | — |
| `meta.stream` | string | ✓ | 70% | — |
| `meta.dt` | string | ✓ | 70% | — |
| `meta.topic` | string | ✓ | 70% | — |
| `meta.partition` | integer | ✓ | 70% | — |
| `meta.offset` | integer | ✓ | 70% | — |
| `id` | integer | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `namespace` | integer | ✓ | 70% | — |
| `title` | string | ✓ | 70% | passport |
| `title_url` | string | ✓ | 70% | passport |
| `comment` | string | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user` | string | ✓ | 70% | — |
| `bot` | boolean | ✓ | 70% | — |
| `notify_url` | string | ✓ | 70% | — |
| `minor` | boolean | ✓ | 70% | — |
| `patrolled` | boolean | ○ | 65% | — |
| `length.old` | integer | ✓ | 70% | — |
| `length.new` | integer | ✓ | 70% | — |
| `revision.old` | integer | ✓ | 70% | — |
| `revision.new` | integer | ✓ | 70% | — |
| `server_url` | string | ✓ | 70% | — |
| `server_name` | string | ✓ | 70% | — |
| `server_script_path` | string | ✓ | 70% | — |
| `wiki` | string | ✓ | 70% | — |
| `parsedcomment` | string | ✓ | 70% | — |

**PII in this cluster:** `meta.uri` (passport), `title` (passport), `title_url` (passport)

---

## `categorize`

- **Events:** 57 (38% of stream)
- **Top-level keys:** meta, id, type, namespace, title, title_url, comment, timestamp, user, bot
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `meta.uri` | string | ✓ | 70% | — |
| `meta.request_id` | string | ✓ | 70% | — |
| `meta.id` | string | ✓ | 70% | — |
| `meta.domain` | string | ✓ | 70% | — |
| `meta.stream` | string | ✓ | 70% | — |
| `meta.dt` | string | ✓ | 70% | — |
| `meta.topic` | string | ✓ | 70% | — |
| `meta.partition` | integer | ✓ | 70% | — |
| `meta.offset` | integer | ✓ | 70% | — |
| `id` | integer | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `namespace` | integer | ✓ | 70% | — |
| `title` | string | ✓ | 70% | — |
| `title_url` | string | ✓ | 70% | — |
| `comment` | string | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user` | string | ✓ | 70% | — |
| `bot` | boolean | ✓ | 70% | — |
| `notify_url` | string | ✓ | 70% | — |
| `server_url` | string | ✓ | 70% | — |
| `server_name` | string | ✓ | 70% | — |
| `server_script_path` | string | ✓ | 70% | — |
| `wiki` | string | ✓ | 70% | — |
| `parsedcomment` | string | ✓ | 70% | — |

---

## `log`

- **Events:** 11 (7% of stream)
- **Top-level keys:** meta, id, type, namespace, title, title_url, comment, timestamp, user, bot
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `meta.uri` | string | ✓ | 70% | ip_address |
| `meta.request_id` | string | ✓ | 70% | — |
| `meta.id` | string | ✓ | 70% | — |
| `meta.domain` | string | ✓ | 70% | — |
| `meta.stream` | string | ✓ | 70% | — |
| `meta.dt` | string | ✓ | 70% | — |
| `meta.topic` | string | ✓ | 70% | — |
| `meta.partition` | integer | ✓ | 70% | — |
| `meta.offset` | integer | ✓ | 70% | — |
| `id` | integer | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `namespace` | integer | ✓ | 70% | — |
| `title` | string | ✓ | 70% | ip_address |
| `title_url` | string | ✓ | 70% | ip_address |
| `comment` | string | ✓ | 70% | — |
| `timestamp` | integer | ✓ | 70% | — |
| `user` | string | ✓ | 70% | — |
| `bot` | boolean | ✓ | 70% | — |
| `log_id` | integer | ✓ | 70% | — |
| `log_type` | string | ✓ | 70% | — |
| `log_action` | string | ✓ | 70% | — |
| `log_params.img_sha1` | string | ○ | 55% | — |
| `log_params.img_timestamp` | string | ○ | 55% | — |
| `log_action_comment` | string | ✓ | 70% | ip_address |
| `server_url` | string | ✓ | 70% | — |
| `server_name` | string | ✓ | 70% | — |
| `server_script_path` | string | ✓ | 70% | — |
| `wiki` | string | ✓ | 70% | — |
| `parsedcomment` | string | ✓ | 70% | — |
| `log_params.duration` | string | ○ | 61% | — |
| `log_params.flags` | string | ○ | 61% | — |
| `log_params.sitewide` | boolean | ○ | 61% | — |
| `log_params.blockId` | integer | ○ | 61% | — |
| `log_params.target` | string | ○ | 54% | — |
| `log_params.noredir` | string | ○ | 54% | — |

**PII in this cluster:** `meta.uri` (ip_address), `title` (ip_address), `title_url` (ip_address), `log_action_comment` (ip_address)

---

## `new`

- **Events:** 9 (6% of stream)
- **Top-level keys:** meta, id, type, namespace, title, title_url, comment, timestamp, user, bot
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `meta.uri` | string | ✓ | 70% | passport |
| `meta.request_id` | string | ✓ | 70% | — |
| `meta.id` | string | ✓ | 70% | — |
| `meta.domain` | string | ✓ | 70% | — |
| `meta.stream` | string | ✓ | 70% | — |
| `meta.dt` | string | ✓ | 70% | — |
| `meta.topic` | string | ✓ | 70% | — |
| `meta.partition` | integer | ✓ | 70% | — |
| `meta.offset` | integer | ✓ | 70% | — |
| `id` | integer | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `namespace` | integer | ✓ | 70% | — |
| `title` | string | ✓ | 70% | passport |
| `title_url` | string | ✓ | 70% | passport |
| `comment` | string | ✓ | 70% | passport |
| `timestamp` | integer | ✓ | 70% | — |
| `user` | string | ✓ | 70% | — |
| `bot` | boolean | ✓ | 70% | — |
| `notify_url` | string | ✓ | 70% | — |
| `minor` | boolean | ✓ | 70% | — |
| `patrolled` | boolean | ✓ | 70% | — |
| `length.new` | integer | ✓ | 70% | — |
| `revision.new` | integer | ✓ | 70% | — |
| `server_url` | string | ✓ | 70% | — |
| `server_name` | string | ✓ | 70% | — |
| `server_script_path` | string | ✓ | 70% | — |
| `wiki` | string | ✓ | 70% | — |
| `parsedcomment` | string | ✓ | 70% | passport |

**PII in this cluster:** `meta.uri` (passport), `title` (passport), `title_url` (passport), `comment` (passport), `parsedcomment` (passport)
