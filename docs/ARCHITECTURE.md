# StreamForge — Architecture Decision Records

This document is the authoritative record of every significant design decision
made in StreamForge. Each ADR (Architecture Decision Record) explains:
  - **Context**: the problem we were solving
  - **Decision**: what we chose
  - **Rationale**: why, and what alternatives we rejected
  - **Consequences**: what this means for future development

The format is inspired by Michael Nygard's original ADR template and the
Spotify/Netflix convention of writing decisions in the present tense
("We use X") rather than the past tense ("We used X").

---

## ADR-001: Layered Configuration Resolution

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Config values come from multiple sources: defaults compiled into
the code, a `config.yaml` the operator edits, and environment variables the
deployment pipeline sets.

**Decision:** Resolution order (highest priority wins):
  1. CLI flags (`--model`, `--interval`, etc.)
  2. Environment variables (`GROQ_API_KEY`, `STREAMFORGE_LOG_LEVEL`, etc.)
  3. `config.yaml` in the project root
  4. Compiled-in defaults in `streamforge/config.py`

**Rationale:** This is the 12-Factor App convention (https://12factor.net/config).
Environment variables are standard in CI/CD and container deployments. Config
files are human-editable and version-controllable. Compiled defaults prevent
surprises when nothing is configured.

**Consequences:** All code receives a `Config` object rather than reading env
vars directly. This makes testing trivial — just pass a different Config.

---

## ADR-002: No Singleton Config Object

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Global singletons are tempting because they're easy to access
from anywhere. But they make testing hard (you can't reset state between tests)
and make dependencies implicit.

**Decision:** `Config` is constructed once in `__main__.py` and passed
explicitly through call stacks. Submodules do not call `config.get()` unless
they are leaf modules with no other way to receive it (e.g., the Streamlit
dashboard).

**Rationale:** Explicit dependency injection is a staff-engineer pattern that
makes the dependency graph visible and testable. The short-term convenience of
a global is not worth the long-term cost.

---

## ADR-003: Secrets Never in config.yaml

**Status:** Accepted
**Date:** 2026-03-14

**Context:** config.yaml is committed to git. API keys, SASL passwords, and
webhook URLs must not appear in git history.

**Decision:** All secrets come exclusively from environment variables. The
config.py `_apply_env()` function reads them. config.yaml has `null` placeholders
for secret fields with comments explaining which env var to set.

**Rationale:** A leaked API key in git history is a permanent security incident.
Environment variables are the standard mechanism for secrets in CI/CD, containers,
and developer machines.

**Consequences:** Operators must configure secrets via env vars or a secrets
manager (AWS Secrets Manager, HashiCorp Vault, GitHub Secrets). This is correct
behaviour — it's not a usability regression.

---

## ADR-004: Structured Logging in Production, Human-Readable in Development

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Log aggregation systems (Datadog, Elastic, Splunk, CloudWatch)
require structured JSON. Developers reading logs in a terminal need human-readable
output.

**Decision:** Two formatters:
  - `HumanFormatter`: colourised, concise, timestamped. Default in dev.
  - `StructuredFormatter`: JSON Lines. Default in CI/production.

Selected via `config.yaml → logging.format` or `STREAMFORGE_LOG_FORMAT` env var.

**Rationale:** Netflix uses structured logging everywhere in production. The
overhead of JSON serialisation is negligible compared to the operational value
of being able to query logs with `jq` or a log aggregation tool.

**Alternatives rejected:** loguru and structlog are excellent libraries but
add a dependency for something the stdlib does adequately.

---

## ADR-005: Resilient Parser with Confidence Scoring

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Real-world event streams contain broken JSON, log-prefixed lines
(e.g., `2026-03-14 14:32:01 INFO {"event_type": "payment"}`), and partially
corrupted records. A strict JSON parser would skip 30-60% of real data.

**Decision:** Three-tier fallback parser returning (dict, confidence_score):
  1. Clean JSON parse → confidence 1.0
  2. Extract embedded JSON fragment from log prefix → confidence 0.7
  3. Regex key:value extraction → confidence 0.5
  4. Unparseable → confidence 0.0, skip

Partial events are tagged with `_partial_extract=True` and included in
clustering/profiling but flagged in reports.

**Rationale:** The profiler's job is to build a picture from whatever data
exists. Skipping 40% of events would produce a schema that doesn't represent
the actual stream. The confidence score lets downstream code distinguish
high-quality events from partial extracts.

---

## ADR-006: Structural Fingerprinting for Sub-Schema Discovery

**Status:** Accepted
**Date:** 2026-03-14

**Context:** A single Kafka topic often contains multiple distinct event shapes.
Example: `payments.stream` might contain `payment_initiated`, `payment_completed`,
and `payment_failed` events. Inferring one flat schema for all of them produces
incorrect presence rates (fields only in `payment_completed` show 33% presence
instead of 100% in their cluster).

**Decision:** Cluster events before inference using:
  1. Known type fields (`event_type`, `type`, `kind`, `schema`) as cluster key
  2. MD5 hash of sorted top-level key names (structural fingerprint)
  3. Sparse events (<2 keys) → `_sparse` bucket
  4. Clusters with <1% of events → merged into `_other`

Each cluster gets its own LLM inference call with cluster-local presence rates.

**Rationale:** This is the core differentiator of StreamForge. Confluent Schema
Registry, AWS Glue, and every competitor treats a topic as having ONE schema.
We treat it as potentially having N schemas.

---

## ADR-007: LLM Tool-Calling for Schema Inference (Not Free Text)

**Status:** Accepted
**Date:** 2026-03-14

**Context:** LLMs can produce schema descriptions in free text, but parsing
free text is fragile and produces inconsistent results.

**Decision:** Force tool-calling (function calling) with a strictly-defined
`submit_inferred_schema` tool. The LLM must call this tool — it cannot respond
in free text. Pydantic validates the tool output before any code uses it.

**Rationale:** Structured output is the only reliable way to get machine-parseable
schemas from an LLM. Netflix's ML platform learned this the hard way — any
free-text parsing in a critical path is a production incident waiting to happen.
Tool-calling is now supported by all major LLM providers (OpenAI, Groq, Anthropic).

---

## ADR-008: Groq by Default, OpenAI-Compatible Interface

**Status:** Accepted
**Date:** 2026-03-14

**Context:** We need an LLM for schema inference. Options: Anthropic Claude,
OpenAI GPT, Groq (hosted Llama), local Ollama.

**Decision:** Default to Groq (`llama-3.3-70b-versatile`) via the OpenAI-compatible
API. The `openai` Python SDK is used with `base_url=https://api.groq.com/openai/v1`.

**Rationale:**
  - Groq has a generous free tier (no credit card required to start)
  - Speed: ~300 tokens/sec vs ~50 for GPT-4o — critical for init on large streams
  - The OpenAI-compatible interface means swapping to OpenAI, Anthropic (via proxy),
    or Ollama requires only a config change, no code change.
  - Groq's free tier supports the init-and-watch pattern well.

**Consequences:** If a user provides `OPENAI_API_KEY` it works. If they provide
`ANTHROPIC_API_KEY` it does NOT work (Anthropic uses a different SDK). They need
a proxy (e.g., LiteLLM) or we add native Anthropic support later.

---

## ADR-009: Statistical Drift Detection (PSI + Binomial Z-Test + Chi-Squared)

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Drift detection could be simple threshold comparisons or rigorous
statistical tests. Simple thresholds have high false positive rates. Statistical
tests have proven industry track records.

**Decision:** Three tests, each used where appropriate:
  - **PSI (Population Stability Index)**: numeric distributions (from banking/ML monitoring)
  - **Binomial Z-test**: presence rate changes (field appearing less often)
  - **Chi-squared**: categorical/enum distributions, type changes

All tests have configurable alpha (default 1% false positive rate). Tests require
a minimum sample size (30) before running; smaller samples fall back to heuristics.

**Rationale:** PSI is the industry standard from model monitoring (used at PayPal,
Goldman Sachs, Netflix ML Platform). It's interpretable: PSI < 0.1 = stable,
0.1–0.2 = slight drift, > 0.2 = significant drift. These thresholds are battle-tested.

---

## ADR-010: Git-Native Schema Storage (No Database)

**Status:** Accepted
**Date:** 2026-03-14

**Context:** StreamForge needs to store schemas, profiles, drift reports, and
policies. Options: a database (PostgreSQL, DynamoDB), a blob store (S3), or
the filesystem with git.

**Decision:** All outputs are YAML/Markdown files on the filesystem, designed
to be committed to git alongside application code.

**Rationale:** This is the Terraform/Kubernetes model. Schemas as code means:
  - Pull requests = schema change review workflow
  - Git history = complete audit trail for compliance
  - Branching = schema experiments without affecting production
  - CODEOWNERS = schema ownership and approval gates
  - Zero extra infrastructure — no database to operate

**Consequences:** Multi-user collaboration requires a git workflow (which is
the right answer anyway). Real-time collaboration (multiple operators watching
the same stream simultaneously) requires coordination outside StreamForge.

---

## ADR-011: Consumer Registry as YAML Alongside schema.yaml

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Blast radius calculation requires knowing which services consume
each stream. We need to store this somewhere.

**Decision:** `consumers.yaml` lives in `schemas/<stream_name>/consumers.yaml`.
It's committed to git alongside `schema.yaml`. A template is generated by
`streamforge init`.

**Rationale:** Same reasons as ADR-010 — git is the right place for this.
The consumer registry is a data contract between producer teams and consumer teams.
It should be reviewed in PRs, have change history, and be owned by the stream's
CODEOWNERS. A database would break all of this.

**Consequences:** Consumer registration is voluntary. Teams adopt it at their
own pace. Streams without `consumers.yaml` get schema governance but not blast
radius analysis — this is acceptable.

---

## ADR-012: Kafka Connector with At-Least-Once Semantics

**Status:** Accepted
**Date:** 2026-03-14

**Context:** StreamForge reads from Kafka for profiling. The connector must
not interfere with production consumer groups or commit offsets incorrectly.

**Decision:** Manual offset commit (at-least-once). Offsets are committed AFTER
successfully processing a batch (via `ack()`), never before. The consumer group
is named `streamforge-profiler` by default — distinct from all production groups.

**Rationale:** At-least-once is always safer than at-most-once for a schema
profiler. A duplicate read means we see a schema element twice — harmless. A
missed read means we might miss an event type in the profile — harmful. If
StreamForge crashes mid-batch, it re-reads from the last committed offset.

---

## ADR-013: kafka-python as Default, confluent-kafka as Optional

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Two main Kafka client libraries exist for Python: `kafka-python`
(pure Python) and `confluent-kafka` (C-based, wraps librdkafka).

**Decision:** Try `confluent-kafka` first (better performance, better SSL support,
active maintenance). Fall back to `kafka-python` if not installed (easier to
install, no native deps).

**Rationale:**
  - `kafka-python` installs everywhere with `pip install` — no librdkafka needed.
    This lowers the adoption barrier (especially on Apple Silicon Macs and CI).
  - `confluent-kafka` is better for production: 5-10x throughput, better SSL/SASL
    support, maintained by Confluent. We prefer it when available.
  - The try/import pattern makes the right choice automatically.

---

## ADR-014: Slack Block Kit for Notifications (Not Plain Text)

**Status:** Accepted
**Date:** 2026-03-14

**Context:** Drift notifications need to be actionable. Plain text webhook
messages are hard to scan at 2am.

**Decision:** Slack Block Kit with:
  - Coloured left border (green/orange/red by tier)
  - Per-field drift breakdown in code formatting
  - Blast radius section (who breaks)
  - Optional "Open Dashboard" action button
  - @here mention for Tier 3 only (configurable)

**Rationale:** Slack Block Kit is the standard for operational alerts in Slack.
It's what PagerDuty, Datadog, and GitHub use. Engineers trust rich alerts — they
contain enough context to act without leaving Slack.

---

## ADR-015: JSON Schema and Avro as Export Formats

**Status:** Accepted
**Date:** 2026-03-14

**Context:** StreamForge uses a proprietary YAML schema format. This is correct
for the source of truth (it's human-editable and contains inference metadata)
but limits interoperability.

**Decision:** Export to:
  - **JSON Schema (Draft 2020-12)**: universal, supported by every validator,
    required by OpenAPI and AsyncAPI.
  - **Apache Avro (.avsc)**: dominant format in Kafka ecosystems, native to
    Confluent Schema Registry.

**Rationale:** Don't invent a new schema standard. Own the workflow of discovering
schemas from messy data and then outputting to the formats teams already use.

**Not exported (yet):** Protobuf, Thrift, Arrow. These can be added as needed.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Event Sources                                   │
│  Kafka Topics  │  NDJSON Files  │  Live Taps (SSE/WebSocket)        │
└───────┬────────┴───────┬────────┴──────────┬──────────────────────┘
        │                │                   │
        ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Connector Layer (connectors/)                      │
│  KafkaConnector  │  FileConnector  │  MockConnector                 │
│  (confluent/kafka-python)  (NDJSON)  (testing)                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │  list[dict] — at-least-once delivery
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Sampler (sampler.py)                               │
│  parse_resilient()  →  reservoir_sample()  →  get_all_field_paths() │
│  Confidence: 1.0 (clean) / 0.7 (partial) / 0.5 (regex) / 0.0 (skip)│
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Profiler (profiler.py)                             │
│  discover_clusters()  →  {cluster_id: [events]}                    │
│  Method: event_type_field | structural_fingerprint | single        │
└────────────────────────────┬────────────────────────────────────────┘
                             │  One cluster at a time
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Inference Engine (inference.py)                    │
│  infer_sub_schema()  →  SubSchema  (one LLM call per cluster)      │
│  Model: Groq llama-3.3-70b (default) | OpenAI | Ollama             │
│  Fallback: statistical_inference() after 3 failures                │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PII Detector (pii_detector.py)                    │
│  Pattern matching + field-name heuristics. No LLM needed.          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
          ┌──────────────────┴──────────────────┐
          ▼                                     ▼
┌─────────────────────┐            ┌────────────────────────┐
│  Schema Writer      │            │  Export (exporters/)   │
│  (schema_writer.py) │            │  JSON Schema / Avro    │
│  profile.yaml       │            │  Confluent Registry    │
│  schema.yaml        │            └────────────────────────┘
│  stream_policy.yaml │
└─────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Drift Detector (drift_detector.py)                 │
│  PSI + Binomial Z-Test + Chi-Squared. Tier 1/2/3 classification.   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          ▼                  ▼                       ▼
┌──────────────────┐ ┌──────────────────┐ ┌────────────────────────┐
│  Report Writer   │ │  Consumer        │ │  Notifications         │
│  (markdown)      │ │  Registry        │ │  (notifications/)      │
│  drift_reports/  │ │  Blast Radius    │ │  Slack / PagerDuty     │
└──────────────────┘ └──────────────────┘ └────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  Dashboard (streamforge_ui.py)                      │
│  Fleet Overview  │  Schema  │  Sub-schemas  │  PII  │  Policy      │
│  Apple Design System. Pure file reader. No backend.                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer              | Technology           | Rationale                                  |
|--------------------|----------------------|--------------------------------------------|
| CLI                | Typer + Rich         | Typed, auto-help, beautiful terminal output |
| Config             | PyYAML + dataclasses | Simple, no magic, git-safe                 |
| LLM               | OpenAI SDK (Groq)    | Model-agnostic, fast, free tier            |
| Data validation    | Pydantic v2          | Type-safe, fast, excellent error messages  |
| Kafka client       | kafka-python         | Pure Python, zero native deps              |
| Drift statistics   | PSI + scipy-free     | Hand-rolled for zero extra deps            |
| Notifications      | httpx                | Already a dependency, async-ready          |
| Dashboard          | Streamlit            | Python-native, fast to iterate             |
| Schema format      | YAML                 | Human-editable, git-diffable               |
| Export formats     | JSON Schema + Avro   | Industry standards, no lock-in             |
