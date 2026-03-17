# StreamForge on Kafka — PoC Deployment Guide

---

## The Core Guarantee

StreamForge is a **passive observer**. It never sits between a producer and a consumer.
It never writes to a topic. It never modifies an offset that a production group owns.

In Kafka's consumer group model, each group independently tracks its own offsets.
StreamForge's group (`streamforge-watcher`) is completely invisible to every other group.

```
                         Producers
                             │
                  ┌──────────▼──────────────┐
                  │   Kafka Topic            │
                  │   (e.g. payments)        │
                  └───┬──────────┬───────────┘
                      │          │           │
              Group A         Group B    streamforge-watcher
              (billing)       (fraud)        │
                      │          │           │
                   consume    consume    reads same bytes
                   (unchanged) (unchanged)  zero impact
```

Producers write once. Every consumer group — including StreamForge — reads its own copy.
StreamForge's lag, crash, restart, or backfill **cannot affect any other group's lag or offset**.

---

## What's Already Built

The Kafka connector (`streamforge/connectors/kafka.py`) is production-ready:

| Feature | Status |
|---|---|
| confluent-kafka (C-based, faster) | ✅ auto-detected if installed |
| kafka-python fallback (pure Python) | ✅ zero native deps |
| PLAINTEXT, SSL, SASL_SSL | ✅ |
| SASL PLAIN, SCRAM-SHA-256/512 | ✅ |
| mTLS (cert + key + CA) | ✅ |
| At-least-once offset commits | ✅ manual commit after `ack()` |
| MSK, Confluent Cloud, Redpanda, Event Hubs | ✅ Kafka protocol compatible |

What needs to be wired for the PoC watch loop:
- Replace file-based `_load_new_events()` with `connector.read_batch()`
- Use Kafka committed offsets as the primary recovery mechanism (the file checkpoint becomes secondary)

**This is a wiring change, not an architecture change.** The EventWindow, drift detector, and all reporting layers are unchanged.

---

## Deployment Topology

### Option A — Same cluster, dedicated node pool (recommended for PoC)

Deploy StreamForge pods in the same Kubernetes cluster as your consumers but on a **separate node pool** labelled `observability`. This gives:
- Network proximity to brokers (low latency reads)
- Resource isolation (StreamForge cannot starve critical consumer pods)
- Same VPC/security group (no new firewall rules needed in most setups)

```
┌─────────────────────────────────────────────────────────────────┐
│  EKS / GKE / AKS Cluster                                        │
│                                                                  │
│  Node pool: production-consumers          Node pool: observability│
│  ┌────────────────────────┐              ┌─────────────────────┐ │
│  │  billing-consumer      │              │  streamforge-watcher│ │
│  │  fraud-consumer        │    Kafka     │  (one pod per topic)│ │
│  │  analytics-consumer    │◄────────────►│                     │ │
│  └────────────────────────┘              └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
             Kafka Brokers
             (MSK / Confluent / self-hosted)
```

### Option B — Separate observability cluster (belt-and-suspenders)

Use Kafka MirrorMaker 2 to replicate topics to a dedicated observability cluster.
StreamForge runs there. No network path between observability and production Kubernetes.
Use this if your security team requires physical isolation.

Tradeoff: adds ~30–60 seconds of replication lag. Fine for schema drift detection (which operates on minutes, not milliseconds).

---

## Kubernetes Deployment

### 1. ConfigMap — stream targets

```yaml
# streamforge-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: streamforge-config
  namespace: observability
data:
  config.yaml: |
    kafka:
      bootstrap_servers:
        - broker-1.kafka.internal:9092
        - broker-2.kafka.internal:9092
        - broker-3.kafka.internal:9092
      security_protocol: SASL_SSL
      sasl_mechanism: SCRAM-SHA-512
      consumer_group: streamforge-watcher   # never changes — keeps offsets stable
      auto_offset_reset: latest             # watch from now forward; use 'earliest' for init
      session_timeout_ms: 30000
      max_poll_records: 500

    watch:
      poll_interval_seconds: 30
      sample_size: 200
      window_capacity: 2000

    output:
      schema_dir: /data/schemas
      drift_report_dir: /data/drift_reports
      webhook_url: ""   # set to Slack/PD webhook URL
```

### 2. Secret — broker credentials

```bash
kubectl create secret generic streamforge-kafka-creds \
  --namespace observability \
  --from-literal=sasl-username=streamforge \
  --from-literal=sasl-password=<password> \
  --from-file=ca.pem=./ca.pem   # if using mTLS
```

### 3. One Deployment per monitored topic

```yaml
# streamforge-payments-watcher.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: streamforge-payments
  namespace: observability
  labels:
    app: streamforge
    topic: payments
spec:
  replicas: 1       # exactly one replica per topic — see Scaling section
  selector:
    matchLabels:
      app: streamforge
      topic: payments
  template:
    metadata:
      labels:
        app: streamforge
        topic: payments
    spec:
      nodeSelector:
        workload: observability      # dedicated node pool
      tolerations:
        - key: observability
          operator: Exists
          effect: NoSchedule

      containers:
        - name: watcher
          image: your-registry/streamforge:latest
          command:
            - streamforge
            - watch
            - kafka://payments          # topic URI — wired in PoC branch
            - --interval
            - "30"
            - --window
            - "2000"
          env:
            - name: STREAMFORGE_KAFKA_SASL_USERNAME
              valueFrom:
                secretKeyRef:
                  name: streamforge-kafka-creds
                  key: sasl-username
            - name: STREAMFORGE_KAFKA_SASL_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: streamforge-kafka-creds
                  key: sasl-password
          resources:
            requests:
              memory: "128Mi"
              cpu: "50m"        # nearly idle between polls
            limits:
              memory: "512Mi"
              cpu: "500m"       # burst headroom for schema inference at init
          volumeMounts:
            - name: schemas
              mountPath: /data/schemas
            - name: config
              mountPath: /etc/streamforge

      volumes:
        - name: schemas
          persistentVolumeClaim:
            claimName: streamforge-schemas-pvc   # stores schema.yaml + window checkpoint
        - name: config
          configMap:
            name: streamforge-config
```

### 4. PersistentVolumeClaim — schema and checkpoint storage

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: streamforge-schemas-pvc
  namespace: observability
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi    # generous — schemas are tiny YAML, checkpoints are NDJSON
  storageClassName: gp3   # AWS; use premium-rwo on GKE, managed-premium on AKS
```

---

## No-Missed-Events Guarantee

Two independent recovery mechanisms work together:

### Mechanism 1 — Kafka committed offsets (primary)

StreamForge commits its offset after every batch via `ack()`. On restart, the Kafka broker serves events from the last committed offset. As long as events are within the topic's **retention window** (default 7 days on most clusters), nothing is missed.

```
Timeline:
  [offset 10,000] ← StreamForge crashes here
  [offset 10,001]    ← events pile up in Kafka log
  [offset 10,002]    ← Kafka retains them (retention: 7 days)
  [offset 10,003]
  ...
  [offset 10,500] ← StreamForge restarts, resumes from offset 10,001
```

The only gap scenario: StreamForge is down **longer than the topic retention period**. For schema monitoring, this is not a concern — if the watcher is down for 7+ days, a manual `init` re-baseline is the right action anyway.

### Mechanism 2 — EventWindow checkpoint (secondary)

The rolling EventWindow is periodically written to `/data/schemas/{stream}/.watch_state/window.ndjson`. On restart, this pre-seeds the window so the first drift check after restart has a statistically stable sample — it doesn't need to wait for 2000 new events before it can detect anything.

This is an optimisation, not a correctness requirement. Without it, the watcher would need 2000 × (1/poll_rate) minutes to warm up. With it, it's ready on the first tick.

### What to set: `auto_offset_reset`

| Command | Setting | Reason |
|---------|---------|--------|
| `init` (one-shot profiling) | `earliest` | Need historical data to build a representative schema |
| `watch` (continuous monitoring) | `latest` | Only care about new events; historical data is already in the schema |

Do not set `watch` to `earliest` unless you're bootstrapping a brand new consumer group — it will re-read the entire topic backlog before starting to monitor live events.

---

## Scaling Model

### One replica per topic (standard)

Schema drift is a topic-level concern, not a partition-level concern. One StreamForge pod consuming all partitions of a topic is the correct model for the PoC. It:
- Sees events from all partitions → statistically representative sample
- Commits one offset per partition (Kafka handles this transparently in consumer groups)
- Uses negligible CPU (~50m) and memory (~128Mi) when idle

```
payments topic (6 partitions)
  Partition 0 ──┐
  Partition 1 ──┤
  Partition 2 ──┤──► streamforge-payments (1 pod, all partitions)
  Partition 3 ──┤
  Partition 4 ──┤
  Partition 5 ──┘
```

### When to add replicas

You would only need more than one replica if:
- The topic produces >100,000 events/second and you need per-partition sampling fidelity
- You want partition-level schema isolation (e.g., events from different producers on different partitions)

In those cases, run one pod per partition with `assign()` instead of `subscribe()`. This is a post-PoC consideration.

### Multiple topics — use a Helm chart or Kustomize

For a PoC monitoring 5 topics:

```bash
for topic in payments orders fraud inventory notifications; do
  helm upgrade --install streamforge-${topic} ./charts/streamforge-watcher \
    --set topic=${topic} \
    --set kafka.bootstrapServers="broker-1:9092,broker-2:9092" \
    --namespace observability
done
```

Each gets its own pod, its own consumer group offset tracking, its own schema directory on the PVC.

---

## Resource Requirements

Per watcher pod (one topic):

| Resource | Request | Limit | Notes |
|---|---|---|---|
| CPU | 50m | 500m | Nearly idle between polls; burst during drift detection |
| Memory | 128Mi | 512Mi | EventWindow at 2000 events × ~2KB avg = ~4MB; rest is headroom |
| Network | ~10KB/poll | — | Only pulls sample_size (200) events per 30s tick |
| Disk (PVC) | 10MB | — | schema.yaml + window checkpoint |

StreamForge never holds a message in memory longer than one poll cycle. It reads a batch, updates the window, runs drift detection, commits the offset, then releases the batch.

---

## Lag Monitoring

StreamForge's consumer lag in Kafka tells you if it's falling behind. Monitor it:

```bash
# Check lag on the payments topic
kafka-consumer-groups.sh \
  --bootstrap-server broker-1:9092 \
  --group streamforge-watcher \
  --describe

# Expected output when healthy:
# GROUP                  TOPIC     PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# streamforge-watcher    payments  0          10,421          10,430          9
# streamforge-watcher    payments  1          8,112           8,115           3
```

Lag of a few seconds is normal and expected — StreamForge reads in 30-second batches by design.
Lag growing unboundedly means the watcher pod is stuck (OOM, deadlock, broker auth failure).

Add a Prometheus alert:

```yaml
- alert: StreamForgeLagHigh
  expr: kafka_consumergroup_lag{group="streamforge-watcher"} > 100000
  for: 10m
  annotations:
    summary: "StreamForge falling behind on {{ $labels.topic }}"
```

---

## Onboarding Phase — Init vs Watch

StreamForge has two distinct operational phases. Understanding the difference is
important for tuning it correctly against a real topic.

```
Phase 1: INIT (onboarding — runs once)        Phase 2: WATCH (continuous — runs forever)
─────────────────────────────────────────     ──────────────────────────────────────────
streamforge init kafka://payments             streamforge watch kafka://payments
  --brokers broker:9092                         --brokers broker:9092
  --sample-size 2000                            --interval 30
                                                --window 2000
                                                --sample-size 200

Reads historical events (offset: earliest)   Reads only new events (offset: latest)
Builds schema.yaml baseline                   Compares incoming events against baseline
Runs once, exits when sample is reached       Runs forever, polls every N seconds
LLM call to infer schema                      No LLM — pure statistical comparison
```

### Init — Onboarding Controls

The two questions to answer before running `init`:

**1. How far back should we read?**

`init` always starts from `auto_offset_reset=earliest` — the oldest event the broker
still has (typically 7 days on most clusters). It reads forward until it reaches
`--sample-size`, then exits.

```bash
# Quick baseline — 500 events, fast
streamforge init kafka://payments --brokers b:9092 --sample-size 500

# Standard baseline — 2000 events, recommended
streamforge init kafka://payments --brokers b:9092 --sample-size 2000

# Deep baseline — read as much history as possible
streamforge init kafka://payments --brokers b:9092 --sample-size 10000
```

**2. How many events is enough?**

| Sample size | When to use |
|-------------|-------------|
| 500 | Quick sanity check, low-traffic topic, single event type |
| 2000 | Standard — catches most schema variants and rare fields |
| 5000–10000 | High-variance streams: many event types, infrequent fields, seasonal patterns |
| 10000+ | Topics where rare fields appear in <1% of events but still matter |

More events = higher schema confidence and more accurate `presence_rate` per field.
The `inference_report.md` shows per-field confidence — if fields are coming back at
0.6–0.7, increase `--sample-size`.

**Iterating on the baseline:**

```bash
# 1. Start small to see what you're dealing with
streamforge init kafka://payments --brokers b:9092 --sample-size 500
cat schemas/payments/inference_report.md   # check per-field confidence

# 2. Low confidence on key fields? Re-init with more history
streamforge init kafka://payments --brokers b:9092 --sample-size 5000

# 3. Happy with the schema? Edit anything the LLM got wrong, then commit
vim schemas/payments/schema.yaml
git add schemas/payments/ && git commit -m "feat: payments schema baseline"
```

The schema.yaml is human-editable — the LLM inference is a starting point, not
the final word. Fix types, add missing fields, tighten enum_values before committing.

---

### Watch — Frequency and Window Controls

```bash
streamforge watch kafka://payments \
  --brokers broker:9092 \
  --interval 30 \       # how often drift detection fires (seconds)
  --window 2000 \       # rolling event buffer size
  --sample-size 200     # events sampled from window per check
```

**`--interval` — how often to check**

| Interval | Use case |
|----------|----------|
| 5–10s | Demo mode, active incident investigation |
| 30s | Standard production (default) |
| 5m | Low-traffic topics, reduce noise on quiet streams |
| 30m | Batch pipelines that publish infrequently |

The interval is also the `read_batch()` timeout for Kafka — StreamForge waits up to
`--interval` seconds for new events to arrive, then runs drift detection with whatever
came in (even zero events — the window still has history).

**`--window` — the rolling event buffer**

The window is what gives the watch loop statistical power. Instead of comparing only
the latest batch against the schema, StreamForge accumulates events in a rolling buffer
and samples from the full population each tick. This makes slow drift detectable.

| Window size | Tradeoff |
|-------------|----------|
| 500 | Reacts fast, but slow drift (field fading over hours) is invisible |
| 2000 | Standard — balances recency vs statistical stability (default) |
| 5000 | Better slow drift detection; uses ~10MB RAM |
| 10000 | Detects fields fading from 80% → 60% presence over 12 hours |

Example of slow drift that only the window catches:
```
Hour 0:  user.loyalty_number present in 85% of events  ← baseline
Hour 4:  user.loyalty_number present in 72% of events  ← small delta, no alert
Hour 8:  user.loyalty_number present in 58% of events  ← delta vs window: DRIFT
```
Without the window, each 30s batch would look only slightly different from the last.
With the window, StreamForge sees the population-level shift and fires.

**`--sample-size` — statistical sample per check**

Events are reservoir-sampled from the window each poll tick. More events = more
statistical power but slightly more CPU per tick (still negligible).

| Sample size | When to increase |
|-------------|------------------|
| 200 | Default — fine for most topics |
| 500 | High-variance streams, many optional fields |
| 1000 | Topics where rare fields appear in 5–10% of events |

---

### Warm-Start After Restart

On restart, StreamForge restores from two sources (in order):

1. **Kafka committed offsets** (primary) — the broker serves events from the last
   committed offset, so no events are missed from the live stream.
2. **Window checkpoint** (secondary) — the rolling EventWindow is persisted to
   `schema_dir/.watch_state/window.ndjson` after every poll. On restart this
   pre-seeds the window so drift detection is immediately statistically meaningful
   without waiting for 2000+ new events to arrive.

This means a pod restart (OOM kill, rolling deploy) causes a brief lag spike that
drains automatically — drift detection resumes within one poll cycle.

---

## PoC Runbook — Steps to Go Live

```bash
# 1. Install with Kafka support
pip install -e ".[kafka]"
# or: pip install confluent-kafka   # recommended
# or: pip install kafka-python      # fallback

# 2. Test connectivity
streamforge kafka-ping payments \
  --brokers broker-1:9092,broker-2:9092 \
  --sasl-username streamforge \
  --sasl-password <secret>

# 3. Run init against the live topic to build the baseline schema
STREAMFORGE_KAFKA_SASL_USERNAME=streamforge \
STREAMFORGE_KAFKA_SASL_PASSWORD=<secret> \
streamforge init kafka://payments \
  --brokers broker-1:9092,broker-2:9092 \
  --sample-size 2000    # read 2000 historical events for a solid schema

# 4. Review the schema before committing it
cat schemas/payments/schema.yaml
cat schemas/payments/inference_report.md

# 5. Commit the schema to git
git add schemas/payments/
git commit -m "feat: add StreamForge schema baseline for payments topic"

# 6. Start the watcher (local test, 10s poll)
streamforge watch kafka://payments \
  --brokers broker-1:9092,broker-2:9092 \
  --schema schemas/payments/schema.yaml \
  --interval 10

# 7. Deploy to Kubernetes
kubectl apply -f k8s/streamforge-payments-watcher.yaml
kubectl -n observability logs -f deploy/streamforge-payments

# 8. Verify it's running clean
kubectl -n observability exec deploy/streamforge-payments -- \
  streamforge report kafka://payments
```

---

## What the PoC Proves

After one week of running:

1. **Zero producer/consumer impact** — confirmed by comparing consumer group metrics before and after StreamForge deployment. No change in lag, throughput, or error rate on any production group.

2. **No missed events** — confirmed by restarting the StreamForge pod and verifying it resumes from the committed offset. Check `kafka-consumer-groups.sh` before and after restart: lag should spike briefly then drain.

3. **Drift detection works** — trigger a known schema change (add a field, change a type) and verify StreamForge raises a drift report within 2–3 poll cycles.

4. **PII detection** — add a field containing an email address or credit card pattern to a test event and verify it appears in the inference report.

The PoC is a success when a data engineer can point StreamForge at a production topic, let it run for 48 hours, and say: "this caught things we would not have seen until a consumer broke."

---

## Known PoC Limitations (Roadmap)

| Limitation | Notes | Planned fix |
|---|---|---|
| Single watcher per topic (no HA) | If the pod restarts, lag grows until it catches up | Leader election via Kafka or ZooKeeper; or StatefulSet with replicated checkpoint |
| Window checkpoint is local (PVC) | Not shared across replicas | Move checkpoint to Redis or S3; use Kafka itself as the offset store |
| `init` reads from `earliest` by default | Large topics take a long time to sample | Add `--max-events` cap and `--start-from-time` flag |
| No Avro/Protobuf deserialisation | Assumes JSON-serialised messages | Add Schema Registry client for Avro; Protobuf descriptor-based deserialiser |
| No per-partition schema variance detection | All partitions treated as one stream | Post-PoC: per-partition sub-schema profiling |
