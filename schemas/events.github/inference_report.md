# Inference Report — events.github

**Inferred:** 2026-03-19T16:05:04.148393+00:00  
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

## Low Confidence Fields (< 80%)

- **`id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`type`** — 70% confidence — Statistically inferred (LLM fallback)
- **`actor_login`** — 70% confidence — Statistically inferred (LLM fallback)
- **`actor_id`** — 70% confidence — Statistically inferred (LLM fallback)
- **`repo_name`** — 70% confidence — Statistically inferred (LLM fallback)
- **`created_at`** — 70% confidence — Statistically inferred (LLM fallback)
- **`push_ref`** — 70% confidence — Statistically inferred (LLM fallback)
- **`push_size`** — 70% confidence — Statistically inferred (LLM fallback)
- **`push_distinct_size`** — 70% confidence — Statistically inferred (LLM fallback)
- **`commit_message`** — 70% confidence — Statistically inferred (LLM fallback)
