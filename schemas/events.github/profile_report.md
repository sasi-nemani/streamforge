# Stream Profile Report — events.github

**Profiled:** 2026-03-19T16:05:04.148393+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Parse success rate:** 100.0%  
**Discovery method:** event_type_field  
**Sub-schemas:** 3

---

## Sub-Schema Summary

| Cluster | Events | % Stream | Fields | Confidence | PII |
|---------|--------|----------|--------|------------|-----|
| `PushEvent` | 124 | 83% | 10 | 60% | — |
| `CreateEvent` | 14 | 9% | 9 | 60% | — |
| `DeleteEvent` | 12 | 8% | 6 | 60% | — |

---

## `PushEvent`

- **Events:** 124 (83% of stream)
- **Top-level keys:** id, type, actor_login, actor_id, repo_name, created_at, push_ref, push_size, push_distinct_size, commit_message
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `id` | string | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `actor_login` | string | ✓ | 70% | — |
| `actor_id` | integer | ✓ | 70% | — |
| `repo_name` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
| `push_ref` | string | ✓ | 70% | — |
| `push_size` | null | ✓ | 70% | — |
| `push_distinct_size` | null | ✓ | 70% | — |
| `commit_message` | null | ✓ | 70% | — |

---

## `CreateEvent`

- **Events:** 14 (9% of stream)
- **Top-level keys:** id, type, actor_login, actor_id, repo_name, created_at, create_ref_type, create_ref, create_description
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `id` | string | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `actor_login` | string | ✓ | 70% | — |
| `actor_id` | integer | ✓ | 70% | — |
| `repo_name` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
| `create_ref_type` | string | ✓ | 70% | — |
| `create_ref` | string | ✓ | 70% | — |
| `create_description` | string | ✓ | 70% | — |

---

## `DeleteEvent`

- **Events:** 12 (8% of stream)
- **Top-level keys:** id, type, actor_login, actor_id, repo_name, created_at
- **Confidence:** 60%

| Field | Type | Required | Confidence | PII |
|-------|------|----------|------------|-----|
| `id` | string | ✓ | 70% | — |
| `type` | string | ✓ | 70% | — |
| `actor_login` | string | ✓ | 70% | — |
| `actor_id` | integer | ✓ | 70% | — |
| `repo_name` | string | ✓ | 70% | — |
| `created_at` | string | ✓ | 70% | — |
