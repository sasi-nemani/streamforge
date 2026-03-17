# StreamForge — System Architecture

**StreamForge is schema contract infrastructure for event streams.**
It infers, enforces, and version-controls schema contracts — the way Terraform manages infrastructure state.

---

## System Diagram

```
EVENT SOURCE                CONTROL PLANE                     CONTRACT ARTIFACTS
(local files /              ─────────────                     ──────────────────
 Kafka-compatible)
                            streamforge init
  events/
  └── payments/             ┌─────────────────────────────┐   schemas/<stream>/
      └── stream_v1/        │  3-Stage Resilient Parser   │     profile.yaml        ← discovery metadata
          ├── 001.ndjson ──▶│  clean JSON    (conf 1.0)   │     schema.yaml         ← enforced contract
          ├── 002.ndjson    │  embedded JSON (conf 0.7)   │     stream_policy.yaml  ← enforcement rules
          └── 003.ndjson    │  regex kv      (conf 0.5)   │     inference_report.md ← per-field audit
                            └────────────┬────────────────┘
                                         │
                            ┌────────────▼────────────────┐
                            │  Cluster Profiler           │
                            │  (profiler.py)              │
                            │  Discovers sub-schemas,     │
                            │  sets routing_field in      │
                            │  profile.yaml               │
                            └────────────┬────────────────┘
                                         │ (one API call)
                            ┌────────────▼────────────────┐
                            │  LLM Inference Engine       │
                            │  (inference.py)             │
                            │  Claude + tool_use          │
                            │  Pydantic-validated output  │
                            └─────────────────────────────┘


DATA PLANE                  ─────────────────────────────────────────────────────

  streamforge watch          streamforge plan
  (continuous)               (one-shot / CI gate)

  ┌──────────────────┐       ┌──────────────────┐
  │  Rolling         │       │  Snapshot sample │
  │  EventWindow     │       │  (no state)      │
  │  2000 events     │       └────────┬─────────┘
  │  checkpoint:     │                │
  │  .watch_state/   │       schema.yaml + stream_policy.yaml
  │  window.ndjson   │                │
  └────────┬─────────┘       ┌────────▼─────────┐
           │                 │  drift_detector  │
  schema.yaml + policy       │  exits 1 on      │
           │                 │  Tier 3 drift    │
  ┌────────▼─────────┐       └──────────────────┘
  │  drift_detector  │         (CI gate — no LLM)
  │  (no LLM)        │
  └────────┬─────────┘
           │
  drift_reports/<stream>/YYYY-MM-DD-HHMM.md
  + console alert + optional webhook POST
```

---

## Contract Artifact Semantics

| Artifact | Role | Who reads it |
|---|---|---|
| `profile.yaml` | Discovery metadata: all clusters found, routing_field, per-cluster field stats | `watch`, `plan`, `export` |
| `schema.yaml` | Enforced contract: primary cluster fields, types, PII flags, enum constraints | Engineers, Git, CI |
| `stream_policy.yaml` | Enforcement rules: tier thresholds, alert targets, CI block behavior | `watch`, `plan` |
| `inference_report.md` | Audit trail: per-field confidence, PII flags, low-confidence warnings | Data engineers, compliance |

`schema.yaml` is the source of truth. Human-editable. Git-committable. `watch` and `plan` enforce it.

---

## Key Architectural Decisions

**1. Layered event parsing.** Three-stage parser handles real-world event heterogeneity without dropping events. Events extracted at lower confidence are flagged `_partial_extract=True` and excluded from inference by default — they still count toward cluster presence rates.

**2. Explicit cluster routing.** `init` writes `routing_field` into `profile.yaml` at onboarding time. During `watch`, cluster assignment is O(1) lookup on that field. For legacy profiles without a routing_field, falls back to structural fingerprint hash.

**3. Rolling EventWindow + NDJSON checkpoint.** `watch` maintains a 2,000-event window persisted to `.watch_state/window.ndjson`. On restart or failover, the window rehydrates from checkpoint — drift signal is statistically stable across process boundaries.

**4. First-class drift semantics.** Three drift classes, each with distinct handling:
- `field_drift` — type change, presence drop, enum expansion (Tier 1–3 based on severity)
- `new_cluster` — unknown event family exceeds 5% of window (Tier 2 by default)
- `cluster_routing_regression` — known cluster drops below 5% of window (Tier 3 — data loss signal)

**5. LLM only at onboarding.** Inference is expensive and one-time. `watch` and `plan` are statistically-driven — zero LLM dependency in the hot path. A schema inferred once enforces indefinitely without further API cost.

---

## Command Surface

| Command | LLM | Purpose |
|---|---|---|
| `init` | Yes (one call) | Infer schema, write all contract artifacts |
| `profile` | No | Field stats + cluster discovery only, no schema written |
| `watch` | No | Continuous drift monitoring against schema.yaml |
| `plan` | No | One-shot drift check; exits 1 on Tier 3 (CI gate) |
| `export` | No | schema.yaml → JSON Schema Draft 2020-12 or Apache Avro |
| `report` | No | Terminal view of schema + drift history |
| `consumers` | No | Consumer registry blast-radius view |

---

## MVP Tradeoffs (honest)

- **File reader simulates Kafka.** Swapping for a real Kafka consumer requires implementing the base connector interface — no changes to inference, drift, or schema layers.
- **Single-instance window state.** One watcher per stream in v1.0. High-availability watch (multiple replicas) requires an external checkpoint store (Redis, S3) instead of the local `.watch_state/` file.
- **Best-effort routing for unknown families.** If a new event family appears that shares no routing_field values with known clusters, `new_cluster` drift fires above the 5% threshold. Cluster assignment is never wrong — it is either known or flagged as new.

---

## Roadmap

**Today:** Local NDJSON, contract inference, drift detection, PII detection, `plan` as CI gate, Git-native schema workflow.

**Next:** Kafka connector (drop-in), webhook/Slack/PagerDuty alerting, persisted offset store for HA watch, policy controls per drift tier.

**Later:** Schema promotion workflow (dev → staging → prod), consumer impact analysis, auto-remediation proposals, compliance audit export.
