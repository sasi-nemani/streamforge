# StreamForge — Architecture Decisions

> Living document. Every significant design or architecture decision is logged here with rationale.
> When a decision changes, update the entry — don't delete it. Record what changed and why.

---

## What Is Built (as of 2026-03-13)

| Module | File | Status |
|--------|------|--------|
| Data models | `streamforge/models.py` | ✅ Built |
| Event loader + reservoir sampler | `streamforge/sampler.py` | ✅ Built |
| PII detector | `streamforge/pii_detector.py` | ✅ Built |
| LLM schema inference | `streamforge/inference.py` | ✅ Built |
| Schema YAML writer + report | `streamforge/schema_writer.py` | ✅ Built |
| Drift detector (heuristic) | `streamforge/drift_detector.py` | ✅ Built — statistical tests pending |
| Drift report writer | `streamforge/report_writer.py` | ✅ Built |
| CLI (`init`, `watch`, `plan`, `report`, `profile`) | `streamforge/__main__.py` | ✅ Built |
| Unit tests | `tests/` | ✅ Built (24 tests, no API calls) |
| Event fixtures (payments, flights, bookings, IoT, GitHub) | `events/` | ✅ Built |
| Connector abstraction layer | `streamforge/connectors/` | ✅ Built (base, file, mock) |
| Statistical drift tests (PSI, z-test, chi-sq) | `streamforge/statistical_tests.py` | ✅ Built (54 tests, pure Python, no scipy) |
| Drift detector — statistical backend | `streamforge/drift_detector.py` | ✅ Updated — presence via binomial z-test, type via chi-squared |
| Onboarding state machine | `streamforge/onboarding.py` | ❌ Not built |
| Sliding window sampler | — | ❌ Not built |
| Policy engine | `streamforge/policy_engine.py` | ❌ Not built |
| Async watch loop | — | ❌ Not built (current loop uses `time.sleep`) |
| Live demo script | `demo/` | ❌ Not built |

---

## Index

| # | Decision | Status |
|---|----------|--------|
| 1 | LLM is not in the drift detection hot path | Decided |
| 2 | Two-phase architecture: onboarding vs. production | Decided |
| 3 | Statistical tests replace heuristic thresholds for drift | Decided |
| 4 | OpenAI-compatible API as the LLM interface | Decided |
| 5 | Connector abstraction: mock-first, then file, then brokers | Decided |
| 6 | schema.yaml is the source of truth | Decided |
| 7 | Pydantic for all internal data types | Decided |
| 8 | PII detection is pattern-first, no LLM | Decided |
| 9 | Reservoir sampling for onboarding, sliding windows for production | Decided |
| 10 | Tool/function calling for structured LLM output | Decided |
| 11 | Statistical fallback when LLM inference fails | Decided |
| 12 | Field-level stability determines when onboarding is complete | Decided |
| 13 | Policy engine owns the action layer, not the drift detector | Decided |
| 14 | Tech stack | Decided |
| 15 | Open source strategy and commercialisation model | Decided |

---

## Decisions

---

### 1. LLM is not in the drift detection hot path

**Status:** Decided
**Date:** 2026-03-13

**Decision:**
The LLM is called only for:
- Initial schema inference during onboarding
- Schema reconstruction after a Tier 3 (critical) drift event
- Generating human-readable explanations of drift

It is never called during routine drift detection. Drift detection runs on pure statistics.

**Rationale:**
At any meaningful scale, calling an LLM per drift check is untenable — cost, latency, and rate limits all prohibit it. The statistical tests (PSI, binomial z-test, chi-squared) are deterministic, fast (<5ms), and have well-understood error rates. The LLM's role is semantic understanding (what is this field, what should it be), not mathematical comparison (has this distribution shifted). These are distinct problems that need distinct tools.

**Consequence:**
The sampler, profiler, and drift detector are LLM-free. The LLM is a one-time cost at onboarding and an exceptional cost on critical drift. This keeps the system runnable without an API key once a schema exists.

---

### 2. Two-phase architecture: onboarding vs. production

**Status:** Decided
**Date:** 2026-03-13

**Decision:**
The system operates in two distinct modes:

- **Onboarding:** Multi-window sampling over time. Builds field-level statistical baselines. LLM infers the initial schema. Phase ends when ≥95% of fields reach stability (see Decision 12).
- **Production:** Continuous sampling. Pure statistical comparison against the baseline. Actions triggered by policy (see Decision 13).

These are not interchangeable. A stream in onboarding is permissive — new fields, type variations, and distribution shifts are expected and absorbed. A stream in production is enforcing a contract.

**Rationale:**
One-shot schema inference from a small sample is brittle. High-cardinality fields (UUIDs, amounts, free-text) need hundreds of samples before a meaningful baseline exists. Low-volume streams may need days to see enough events to represent normal variance. Trying to run drift detection before the baseline is stable generates noise. Separating onboarding from production makes the state explicit and the guarantees clear.

---

### 3. Statistical tests replace heuristic thresholds for drift detection

**Status:** Decided — implemented (Phase 1 complete)
**Date:** 2026-03-13

**Decision:**
Drift detection uses established statistical tests per field type. Heuristic thresholds are retained only as backstops when n < 30 (normal approximation invalid).

| Signal | Test | α | Fall-through (n<30) |
|--------|------|---|---------------------|
| Presence rate change | Binomial z-test | 0.01 | Absolute threshold (±15pp) |
| Type distribution change | Chi-squared (Pearson) | 0.01 | Fraction threshold (>5%) |
| Numeric value distribution | PSI (Population Stability Index) | — | PSI > 0.20 |
| Categorical new values | Set difference + frequency | — | >5% novel values |

**Implementation notes (2026-03-13):**
- `streamforge/statistical_tests.py` — pure Python, zero dependencies beyond stdlib. No scipy. Uses `math.erfc` (always available) for the normal survival function. Uses a Kummer series fallback for chi-squared when Python < 3.11 (where `math.gammaincc` is unavailable). Bug found during implementation: the series fallback was double-dividing by Γ(a) and underflowing for large χ² — both fixed.
- Both tests are pure functions: deterministic, no I/O, independently testable.
- `STREAMFORGE_STAT_ALPHA` env var controls the significance threshold globally.

**Rationale:**
Heuristic thresholds have two failure modes at scale:
1. False positives on low-volume streams (small sample → high variance → threshold fires on noise)
2. False negatives on high-volume streams (slow gradual drift never breaches a fixed threshold)

Statistical tests adapt to sample size. PSI is the industry standard in financial risk monitoring (all major banks) and ML pipeline monitoring (Google TFX, LinkedIn Deequ). Binomial z-test is the standard test for rate changes under Bernoulli assumptions (exactly what presence rate is).

---

### 4. OpenAI-compatible API as the LLM interface

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
All LLM calls use the OpenAI function-calling API format via the `openai` Python SDK with a configurable `base_url` and `--model` flag. No vendor-specific SDK is used.

**Rationale:**
The OpenAI API format is the de-facto standard. Every major provider (Groq, Mistral, Together, OpenRouter) and every local inference engine (Ollama, vLLM, LM Studio) supports it. Locking to a vendor SDK means a rewrite to switch providers. Two flags change the entire inference stack.

**Recommended providers by stage:**
| Stage | Provider | Model | Cost |
|-------|----------|-------|------|
| Dev / free | Groq | `llama-3.3-70b-versatile` | Free tier |
| Local dev | Ollama | `qwen2.5-coder:7b` | Zero |
| Production local | vLLM | `Qwen2.5-Coder-7B-Instruct` | Hardware only |
| Managed | OpenAI | `gpt-4o-mini` | ~$0.02/inference |

**Recommended local model:** `qwen2.5-coder:7b` — trained specifically on code and structured data tasks, reliable function calling, runs on 8GB RAM.

---

### 5. Connector abstraction: mock-first, then file, then brokers

**Status:** Decided — MockConnector + FileConnector implemented, Redis Streams pending
**Date:** 2026-03-13

**Decision:**
All stream sources implement a single `StreamConnector` abstract interface. The system never knows or cares what the source is. Build order: MockConnector → FileConnector (done) → Redis Streams → Kafka → SQS/SNS.

**No Kafka cluster required to develop or demo.** The `MockConnector` generates events programmatically in-process. The `FileConnector` (already built) handles all current testing. Redis Streams is the first real broker connector — it runs as a single Docker container, zero configuration.

**The interface contract:**
```python
class StreamConnector(ABC):
    async def read_batch(self, max_messages: int, timeout_ms: int) -> list[dict]: ...
    async def ack(self) -> None:   # commit offset / delete message / advance cursor
    async def close(self) -> None: ...
```

**Connector roadmap:**
| Connector | Dependency | Demo use | Production use |
|-----------|------------|----------|----------------|
| `MockConnector` | None | ✅ Primary demo source | Load testing |
| `FileConnector` | None | ✅ Already works | Log file ingestion |
| `RedisStreamConnector` | `redis-py` + Docker | ✅ Real broker demo | Low-volume production |
| `KafkaConnector` | `confluent-kafka` | When cluster available | High-volume production |
| `SQSConnector` | `boto3` | AWS demo | AWS production |

**Why Redis Streams over Kafka for demo:**
- Single `docker run redis` — no cluster, no ZooKeeper, no broker config
- Redis Streams is a real persistent log (not a queue) — semantically identical to Kafka for this use case
- Consumer groups, offsets, and ack work the same way
- `pip install redis` — one dependency

**Rationale for mock-first:**
A `MockConnector` that generates configurable event streams (including injecting drift on a schedule) is the most powerful demo tool. It requires no external infrastructure, runs identically on any machine, and lets you demonstrate schema inference + drift detection + real-time alerting in a single `python demo/run.py`.

---

### 6. schema.yaml is the source of truth

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
The inferred schema is written to a human-readable `schema.yaml` file. This file is the contract. It is designed to be committed to git, reviewed in pull requests, and edited by hand when corrections are needed. The drift detector reads from this file, not from a database.

**Rationale:**
"Terraform for data schemas" is the product framing. Terraform's power comes from the plan file being a readable artifact that humans review before applying. A database-backed schema store would make the contract invisible. Git-backed YAML gives version history, blame, PR review, and rollback for free. Engineers can correct a bad inference by editing the file — no UI, no API, no tooling required.

**Consequence:**
The schema store is a filesystem. When this scales beyond a single machine, the filesystem becomes a git repo with a remote. Only if concurrent writes from multiple workers become a problem does this need rethinking — and that is a Phase 3 problem.

---

### 7. Pydantic for all internal data types

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
All internal data structures (`FieldSchema`, `InferredSchema`, `FieldDrift`, `DriftReport`) are Pydantic v2 models defined in `models.py`. No ad-hoc dicts cross module boundaries.

**Rationale:**
LLM outputs are untrustworthy. Pydantic validation at the boundary between the LLM response and the rest of the system catches malformed output before it propagates. Typed models make module interfaces explicit and catch integration bugs at import time rather than at runtime.

---

### 8. PII detection is pattern-first, no LLM

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
PII detection uses two stages, both without LLM:
1. Field name heuristics — segment-level matching against a known hint list
2. Regex pattern matching on sample values (email, passport, card, IP, phone)

**Implementation details:**
- Hints match against individual dot-notation path segments, not the full path string — prevents `"ip"` matching `"subscriptions_url"`
- Short hints (≤4 chars): exact segment match only
- Longer hints (e.g. `"frequent_flyer"`): substring of segment
- Phone detection requires phone-formatting characters (spaces, dashes, `+`) — bare digit strings (numeric IDs, epoch timestamps) are not flagged

**Known limitation:**
Free-text fields with embedded PII (a `notes` field containing a phone number in running text) are not caught. Post-MVP concern.

---

### 9. Reservoir sampling for onboarding, sliding windows for production

**Status:** Decided — reservoir implemented, sliding windows pending
**Date:** 2026-03-13

**Decision:**
- **Onboarding:** Algorithm R reservoir sampling — uniform random sample from all events seen so far. Appropriate because all history is equally informative for building a baseline.
- **Production:** Sliding time-window sampling — recent events weighted more heavily. Answers "is this stream drifting *now*?", not "has it ever drifted?"

**Rationale:**
Reservoir sampling loses temporal signal. If a field drifted 10 minutes ago but the reservoir has 490 pre-drift and 10 post-drift events, the drift signal is 2% — below any threshold. A 30-minute sliding window shows it at 100%. Production drift detection requires recency.

**Current state:** Reservoir sampling used for both modes. Sliding window sampler is Phase 2.

---

### 10. Tool/function calling for structured LLM output

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
All LLM inference calls use function/tool calling with forced tool choice. The model is never allowed to respond in free text.

**Rationale:**
Parsing JSON from free-text LLM output is fragile — markdown fences, added commentary, omitted required fields, subtly invalid JSON. Tool calling with forced tool choice gives a binary outcome: valid structured response or clean retryable error. The retry loop (3 attempts → statistical fallback) handles edge cases.

---

### 11. Statistical fallback when LLM inference fails

**Status:** Decided — implemented
**Date:** 2026-03-13

**Decision:**
After 3 failed LLM inference attempts, the system falls back to statistical type inference — majority vote on observed Python types, confidence capped at 0.7.

**Rationale:**
A failed `streamforge init` is worse than a low-confidence schema. The statistical fallback produces a usable schema the operator can correct by editing the YAML. The confidence cap (≤0.7) signals clearly that human review is needed. The system degrades gracefully.

---

### 12. Field-level stability determines when onboarding is complete

**Status:** Decided — not yet implemented
**Date:** 2026-03-13

**Decision:**
Onboarding is event-driven, not time-driven. Each field reaches `STABLE` state when:
- Sample count exceeds a type-appropriate minimum (strings: 200, categoricals: 50× cardinality, numerics: 500)
- Type distribution unchanged across 3 consecutive sampling windows
- For categoricals: no new values in the last window

Schema declared ready when ≥95% of fields are stable AND minimum 72h of data observed (to capture at least one weekday/weekend cycle).

**Rationale:**
Time-based cutoffs ignore volume. A high-volume payments stream stabilises in hours. A weekly report event may need weeks to show full field variation. Stability criteria are grounded in what is actually needed: enough samples to trust the type inference and distribution baseline.

---

### 13. Policy engine owns the action layer, not the drift detector

**Status:** Decided — not yet implemented
**Date:** 2026-03-13

**Decision:**
The drift detector produces a `DriftReport` with tier classification. It does not decide what to do. A policy engine reads per-stream `stream_policy.yaml` and routes the drift event to configured actions.

**Action types:**
- `log` — write to drift report, no alert
- `alert` — Slack / PagerDuty / webhook
- `propose_correction` — generate schema patch, await human ack
- `auto_apply_after: Nh` — apply if no human ack within N hours
- `block_pipeline` — halt downstream consumers
- `trigger_reinference` — rebuild schema with LLM

**Rationale:**
Different streams have different stakes. Tier 2 drift on a low-criticality analytics stream should log silently. The same drift on a payments stream should page on-call. Hardcoding actions in the drift detector couples detection to operational policy — they change for completely different reasons.

---

### 14. Tech stack

**Status:** Decided
**Date:** 2026-03-13

#### Core (OSS — ships with `pip install streamforge-cli`)

| Layer | Library | Notes |
|-------|---------|-------|
| Language | Python 3.11+ | Data engineering ecosystem standard |
| Data models | Pydantic v2 | Already in place |
| CLI | Typer + Rich | Already in place |
| Statistical tests | SciPy + NumPy | PSI, binomial z-test, chi-squared |
| LLM interface | `openai` SDK | Provider-agnostic via base_url |
| Schema serialisation | PyYAML | Already in place |
| Async runtime | `asyncio` + `anyio` | Replace `time.sleep` watch loop with true async multi-stream workers |
| Onboarding state | SQLite (stdlib) | Zero-dependency persistence, swappable for Postgres |
| Connector: files | stdlib | Already built in `sampler.py` |
| Connector: Redis Streams | `redis-py` | Simplest real broker, single Docker container |
| Connector: Kafka | `confluent-kafka` | When a cluster is available |
| Connector: SQS/SNS | `boto3` | AWS environments |
| Webhooks / HTTP | `httpx` | Already a dependency |
| Packaging | hatchling + PyPI | Already in place |
| Container | Docker + docker-compose | For demo: event generator + StreamForge |

#### Production / self-hosted control plane (commercial layer)

| Layer | Library | Notes |
|-------|---------|-------|
| API | FastAPI | Async, auto OpenAPI docs |
| Schema store (at scale) | PostgreSQL + SQLAlchemy | When filesystem is insufficient |
| Real-time drift events | Redis pub/sub | Web UI and webhooks subscribe |
| Observability | OpenTelemetry | Vendor-neutral traces + metrics from day one |

#### What is explicitly NOT in the stack (and why)
- **No Spark / Flink** — batch processing frameworks add operational complexity not justified by the problem. Statistical tests on samples run in milliseconds with SciPy.
- **No ML framework** — drift detection is classical statistics, not ML. NumPy + SciPy is the entire compute layer.
- **No message bus between internal components** — this is a single-process tool. Internal coupling via function calls is appropriate at this stage.

---

### 15. Open source strategy and commercialisation model

**Status:** Decided
**Date:** 2026-03-13

**License:** Apache 2.0
- Business-friendly, allows commercial use without copyleft obligations
- Standard in the data engineering ecosystem (Kafka, Spark, Airflow, dbt are all Apache 2.0)
- Allows proprietary features to be built on top

**Repository structure:**
```
streamforge/                     ← OSS monorepo
├── streamforge-core/            ← pip install streamforge-cli
├── streamforge-connectors/      ← pip install streamforge-connectors (3rd-party brokers)
├── streamforge-server/          ← commercial/self-hosted control plane
└── demo/                        ← docker-compose demo, runs with no external dependencies
```

**Open core split:**

| OSS (always free) | Commercial (StreamForge Cloud / Enterprise) |
|-------------------|---------------------------------------------|
| CLI | Web UI + schema browser |
| File / Redis / Kafka / SQS connectors | SSO / RBAC |
| Schema inference (LLM) | Managed schema registry |
| Statistical drift detection | Audit logs + compliance reports |
| Profiler | Enterprise connectors (Splunk, Datadog, Segment) |
| schema.yaml format | SLA + support |
| Policy engine (local config) | Multi-tenant control plane |

**Principle:** The OSS core must be genuinely useful standalone. No artificial feature crippling. Commercialisation comes from operations, scale, and enterprise requirements — not from withholding core functionality. This is the dbt / Airbyte / Grafana model.

---

## Build Phases

### Phase 0 — MVP (complete)
`init`, `watch`, `plan`, `report`, `profile` commands working. LLM inference via Groq. File-based event source. Heuristic drift detection. PII detection. schema.yaml output.

### Phase 1 — Statistical foundation (next)
- `streamforge/connectors/base.py` — abstract interface
- `streamforge/connectors/mock.py` — in-process event generator for demo
- `streamforge/statistical_tests.py` — PSI, binomial z-test, chi-squared
- Replace heuristics in `drift_detector.py` with statistical tests
- Async watch loop (replace `time.sleep`)

### Phase 2 — Onboarding + temporal sampling
- `streamforge/onboarding.py` — field stability state machine
- Sliding window sampler
- `stream_policy.yaml` schema + loader
- `streamforge/policy_engine.py` — action router

### Phase 3 — Demo + connectors
- `streamforge/connectors/redis_stream.py`
- `demo/` — self-contained demo with MockConnector injecting drift on a timer
- `docker-compose.yml` — StreamForge + Redis + event generator, one command

### Phase 4 — Production
- `streamforge/connectors/kafka.py` — confluent-kafka
- `streamforge/connectors/sqs.py` — boto3
- FastAPI control plane
- OpenTelemetry instrumentation

---

## Decisions Pending

| Topic | Question | Target phase |
|-------|----------|-------------|
| Sliding window | Window size, eviction policy, memory cap per stream | Phase 2 |
| Onboarding state persistence | SQLite schema, migration strategy | Phase 2 |
| PSI bucket count | 10 vs 20 buckets — trade-off between sensitivity and stability | Phase 1 |
| Redis Streams vs NATS | NATS is lighter but less familiar to data engineers | Phase 3 |
| Schema store at scale | Git-backed filesystem vs PostgreSQL — trigger condition | Phase 4 |
| Demo drift injection | Timer-based vs event-count-based drift trigger in MockConnector | Phase 3 |
