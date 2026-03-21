# Inference Report — events.wikipedia

**Inferred:** 2026-03-19T16:05:09.595843+00:00  
**Model:** llama-3.3-70b-versatile  
**Events sampled:** 150  
**Overall confidence:** 60%

---

## Ingest Quality

| Total events | Clean (used for inference) | Partial (excluded) | Parse rate |
|---|---|---|---|
| 150 | 150 | 0 | 100.0% |

---

## Field Summary

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

---

## PII Fields

- **`meta.uri`** — passport
- **`title`** — passport
- **`title_url`** — passport

---

## Low Confidence Fields (< 80%)

- **`meta.uri`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.request_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.domain`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.stream`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.dt`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.topic`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.partition`** — 70% confidence — Statistically inferred (LLM fallback)
- **`meta.offset`** — 70% confidence — Statistically inferred (LLM fallback)
- **`id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`namespace`** — 70% confidence — Statistically inferred (LLM fallback)
- **`title`** — 70% confidence — Statistically inferred (LLM fallback)
- **`title_url`** — 70% confidence — Statistically inferred (LLM fallback)
- **`comment`** — 70% confidence — Statistically inferred (LLM fallback)
- **`timestamp`** — 70% confidence — Statistically inferred (LLM fallback)
- **`user`** — 70% confidence — Statistically inferred (LLM fallback)
- **`bot`** — 70% confidence — Statistically inferred (LLM fallback)
- **`notify_url`** — 70% confidence — Statistically inferred (LLM fallback)
- **`minor`** — 70% confidence — Statistically inferred (LLM fallback)
- **`patrolled`** — 65% confidence — Statistically inferred (LLM fallback)
- **`length.old`** — 70% confidence — Statistically inferred (LLM fallback)
- **`length.new`** — 70% confidence — Statistically inferred (LLM fallback)
- **`revision.old`** — 70% confidence — Statistically inferred (LLM fallback)
- **`revision.new`** — 70% confidence — Statistically inferred (LLM fallback)
- **`server_url`** — 70% confidence — Statistically inferred (LLM fallback)
- **`server_name`** — 70% confidence — Statistically inferred (LLM fallback)
- **`server_script_path`** — 70% confidence — Statistically inferred (LLM fallback)
- **`wiki`** — 70% confidence — Statistically inferred (LLM fallback)
- **`parsedcomment`** — 70% confidence — Statistically inferred (LLM fallback)
