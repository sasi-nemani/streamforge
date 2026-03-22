# StreamForge Production Readiness

Last updated: 2026-03-15

## Status

Current assessment: strong MVP, not yet production-ready for high-volume Kafka deployment.

What is solid:

- canonical schema inference is less likely to be polluted by partial parses
- rolling watch windows make slow drift detection plausible
- multi-schema streams are now recognized and enforced better than before
- the test suite is broad enough for MVP confidence

What still blocks production readiness:

- file-based watch semantics remain the dominant runtime assumption
- multi-schema enforcement still has a split source of truth between `profile.yaml` and `schema.yaml`
- state management is local and single-process
- Kafka ingestion exists as a connector but is not integrated into the main operational path

## Highest Priority Findings

### P1 — Multi-schema enforcement still uses a primary-cluster compatibility schema as the human-edited contract

Files:
- [streamforge/__main__.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/__main__.py#L219)
- [streamforge/schema_writer.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/schema_writer.py#L182)
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L889)

Problem:
- `init` persists all discovered sub-schemas into `profile.yaml`, but still writes `schema.yaml` from only the primary cluster.
- `watch_stream()` then prefers rebuilding baseline state from `profile.yaml` in multi-schema mode instead of the human-edited `schema.yaml`.

Risk:
- the operator-facing contract and the runtime-enforced contract can diverge silently
- edits to `schema.yaml` may not be the authoritative enforcement path for multi-schema streams

Why this breaks in production:
- platform teams need one clear source of truth
- during incident response, ambiguous authority between two files is unacceptable

Recommended fix:
- define one canonical contract model for multi-schema streams
- either:
  - make `profile.yaml` the enforced contract and explicitly deprecate `schema.yaml` for multi-schema streams, or
  - make `schema.yaml` contain all enforced sub-schemas

### P1 — Kafka connector is not integrated into the actual `init` / `watch` / `plan` path

Files:
- [streamforge/connectors/kafka.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/connectors/kafka.py#L1)
- [streamforge/__main__.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/__main__.py#L72)

Problem:
- there is a serious Kafka connector implementation, but the core CLI still assumes local folder paths
- the watch loop and sampling semantics are file-based rather than offset/partition-based

Risk:
- production teams may assume Kafka readiness from the connector existing in-repo, but the operational path is not wired for it

Why this breaks in production:
- you need:
  - consumer-group semantics
  - partition-aware replay
  - checkpointed offsets
  - exactly what constitutes the watch window over partitions

Recommended fix:
- add a connector abstraction into the actual runtime path
- make `init`, `plan`, and `watch` operate over a `StreamConnector` interface rather than only folders

### P1 — Watcher state is local-file checkpointing, not distributed or HA-safe

Files:
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L533)
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L909)

Problem:
- rolling window state is checkpointed into `.watch_state/window.ndjson` beside the schema directory
- this is restart-friendly on one node but not coordinated across replicas

Risk:
- duplicate or divergent windows across watcher replicas
- failover is approximate rather than deterministic
- no shared lease/ownership or rebalance model

Why this breaks in production:
- any serious Kubernetes deployment will want multiple watcher replicas or controlled failover
- local disk state is not enough for HA semantics

Recommended fix:
- move runtime watch state to a durable shared store
- likely choices:
  - Kafka offsets + compacted state topic
  - Redis for ephemeral distributed coordination
  - Postgres for control-plane state if throughput is modest

### P1 — Cluster routing still falls back to structural fingerprints and legacy heuristics

Files:
- [streamforge/profiler.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/profiler.py#L22)
- [streamforge/profiler.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/profiler.py#L92)
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L602)

Problem:
- explicit `routing_field` is now stored, which is good
- but routing still falls back to scanning `_TYPE_FIELDS` and recomputing structural hashes for legacy or structural streams

Risk:
- slight producer shape changes can create routing churn before clean drift classification
- structural hashes are a weak long-term contract key

Why this breaks in production:
- routing identity must be stable across deploys, backfills, and schema evolution

Recommended fix:
- persist a stronger routing contract in the profile/contract artifact
- explicitly store:
  - routing mode
  - routing field name if applicable
  - canonical cluster key definition
  - fallback behavior for unmatched events

### P1 — Persisted schema reload does not reconstruct PII enums correctly

Files:
- [streamforge/schema_writer.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/schema_writer.py#L300)
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L360)

Problem:
- `load_schema()` assigns `pii_categories=fd.get("pii", [])` directly from YAML.
- elsewhere, PII logic compares against `PIICategory` enum values.

Risk:
- loaded schemas can carry strings where the runtime expects enums
- new-PII comparisons can become inconsistent between fresh in-memory schemas and schemas loaded from disk

Why this breaks in production:
- persisted contracts are the normal path in production, not ephemeral in-memory objects
- any mismatch between serialized and runtime types will create hard-to-debug alert quality issues

Recommended fix:
- normalize PII values back into `PIICategory` enums inside `load_schema()`
- add a regression test that loads a schema from disk and verifies `new_pii` detection behavior

## Medium Priority Findings

### P2 — Small-cluster behavior can hide real drift in sparse traffic

Files:
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L770)

Problem:
- clusters with fewer than 5 matched events are skipped

Risk:
- low-volume but important event families may never trigger drift detection during sparse periods

Recommended fix:
- introduce sparse-cluster policy controls
- allow cluster-specific thresholds or time-window accumulation

### P2 — Sampling/window strategy is still generic reservoir sampling rather than risk-aware sampling

Files:
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L963)
- [streamforge/sampler.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/sampler.py#L139)

Problem:
- reservoir sampling is simple and correct for uniform samples
- but production drift often lives in rare partitions, rare tenants, or bursty sub-families

Risk:
- important rare regressions are under-sampled

Recommended fix:
- support weighted or stratified sampling by cluster, partition, or key

### P2 — File-based line-count tracking does not map cleanly to production stream semantics

Files:
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L951)

Problem:
- `_load_new_events()` uses line counts and reseeding assumptions suitable for local files

Risk:
- not reusable as-is for Kafka, Kinesis, Pub/Sub, or SQS

Recommended fix:
- move source-specific progression logic into connectors
- keep the drift engine source-agnostic

### P2 — Window checkpoint rewrites the full buffer every poll

Files:
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L533)
- [streamforge/drift_detector.py](/Users/sasidharnemani/Documents/streamforge-mvp-full/streamforge-mvp/streamforge/drift_detector.py#L987)

Problem:
- `_save_checkpoint()` rewrites the entire event window to disk after every successful poll

Risk:
- write amplification grows with window size and poll frequency
- this is acceptable for MVP demo volumes but becomes unnecessary I/O pressure at production rates

Recommended fix:
- move from full-window rewrites to append-plus-compaction or broker-backed state
- treat the current checkpointing logic as a local-demo mechanism, not a production design

## Readiness Checklist

### Contract Model

- [ ] define the single enforced contract artifact for multi-schema streams
- [ ] document operator editing behavior for multi-schema streams
- [ ] add migration rules for old `profile.yaml` files

### Kafka Runtime

- [ ] wire `StreamConnector` into `init`, `plan`, and `watch`
- [ ] define partition and offset semantics for sampling
- [ ] add replay-safe checkpointing for Kafka consumers
- [ ] test rebalances and restarts

### Watcher Reliability

- [ ] move watch state off local disk for HA deployments
- [ ] add leader election or shard ownership
- [ ] define duplicate-handling and replay expectations

### Drift Quality

- [ ] support sparse-cluster accumulation
- [ ] add stratified or weighted sampling options
- [ ] benchmark slow-drift sensitivity over long windows

### Operability

- [ ] add SLOs for watch lag, drift detection latency, and false-positive rate
- [ ] emit structured metrics for sample/window size and cluster-match rate
- [ ] document runbooks for new-cluster and routing-regression drift types

## Deployment Stack Recommendation

### Recommended production stack for high-volume deployment

- Kubernetes for orchestration
- Strimzi-managed Apache Kafka or Redpanda for the event backbone
- object storage for archived raw samples and reports
- Postgres for control-plane metadata
- Redis only if you need fast distributed coordination before Kafka-native state is implemented
- Prometheus + Grafana for metrics
- Loki or OpenSearch for logs
- Tempo or Jaeger for tracing if the control plane becomes service-based

### Why this stack

- Kubernetes gives a standard operator model for watchers, control-plane APIs, and UI services
- Kafka remains the right backbone for ordered, replayable, partitioned event ingestion
- Postgres is enough for contract metadata, policy state, and audit history
- object storage is the cheapest place for historical samples and generated reports

### Suggested service split

- `streamforge-api`
  manages schemas, profiles, policies, and report metadata
- `streamforge-init-worker`
  runs inference and profile generation jobs
- `streamforge-watch-worker`
  runs continuous drift detection per assigned stream/topic shard
- `streamforge-ui`
  reads from API/control-plane state instead of local files

### What not to do for prod

- do not use local filesystem as the primary shared state model
- do not run one giant watcher process for all topics
- do not let the UI read production state directly from per-pod disks

## Notes For Future Updates

Whenever production-related changes land:

- mark impacted findings as resolved, mitigated, or still open
- add file references
- record any new assumptions around Kafka semantics, routing, or HA behavior
