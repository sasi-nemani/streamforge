# StreamForge

> **Know what's in your event streams — and what breaks when you change them.**
> Read-only schema discovery, cross-topic lineage, and drift detection for Kafka, SQS and message queues.

Most event estates have no enforced contract: hundreds of topics and queues, some built years
ago by people who've moved on, some external feeds you can't change. A producer renames one
field and downstream systems break hours later — and nobody can say what depended on it.

StreamForge **infers the contract directly from the messages** — read-only, no producer
changes, no registry to adopt — then watches for breaking drift and shows the **blast radius**
of a change across topics and consumers before it ships.

## What it does

- **Discover** — sample live traffic and infer a typed schema per stream (types, presence
  rates, enums, PII), written as version-controlled YAML. Deterministic by default.
- **Map** — a cross-topic dependency graph: where each field lives, where the *same field is
  typed differently across teams*, and which consumers read it (including a runtime observer
  that records the fields consumers *actually* access).
- **Watch** — statistical drift detection (binomial-z, chi-squared, PSI) under
  Benjamini–Hochberg FDR control, so hundreds of simultaneously-tested fields don't drown
  you in false positives. Every alert carries its evidence (test, p-value, effect size).
- **Block** — `streamforge plan` exits 1 on breaking drift; plug it into any CI pipeline.

## Quickstart (2 minutes, no Kafka, no API key)

Runs fully offline against the bundled sample streams:

```bash
git clone https://github.com/nskq4b6gmv-rgb/streamforge-mvp.git
cd streamforge-mvp
pip install -e .

# 1. Infer a schema — deterministic, no LLM, no key
python -m streamforge init events/payments/stream_v1 --offline

# 2. Prove it works — scores itself against hand-labelled ground truth
python -m streamforge eval

# 3. Detect drift — compare a drifted stream against the contract (exits 1)
python -m streamforge plan events/payments/stream_v2_drift \
    --schema schemas/stream_v1/schema.yaml
```

With a real broker: `streamforge discover --brokers localhost:9092`, then
`init kafka://<topic>` / `watch kafka://<topic>`. An optional LLM (any OpenAI-compatible
endpoint, self-hosted included) adds semantic types (uuid / email / timestamp) on first
sight of a novel shape; a structural-fingerprint cache means repeated shapes never call
it again.

## Commands

| Command | What it does |
|---------|--------------|
| `discover` | Inventory every topic/queue with governance status |
| `init` | Infer a schema from live events (`--offline` = deterministic, no LLM) |
| `watch` | Continuous drift monitoring loop |
| `plan` | One-shot drift check — exits 1 on breaking drift (CI gate) |
| `eval` | Score inference + drift against labelled benchmarks (P/R/F1, calibration) |
| `profile` | Multi-schema profiling for mixed-event-type topics |
| `report` / `incident-report` | Schema + drift history, structured incident summaries |
| `export` | Convert schemas to JSON Schema, Avro, Protobuf, Flink DDL, ksqlDB |

A React cockpit (`cockpit/` + `streamforge/api/`) visualises the cross-topic dependency
map, per-field blast radius and drift evidence. A CI example lives in `streamforge-action/`.

## Where it fits (honestly)

| You have | Use |
|----------|-----|
| Avro/Protobuf discipline + Confluent/Glue registry on Kafka | **Keep your registry.** StreamForge adds statistical drift, cross-topic lineage, and coverage of what the registry can't see — and can push schemas to it. |
| Raw-JSON topics, legacy MQ (SQS/IBM MQ), external partner feeds | This is the gap StreamForge is built for: contracts inferred from the wire, with no registration and no producer changes. |
| A data catalog (DataHub/OpenMetadata/Collibra) | StreamForge complements it — stream-level inference and drift can feed the catalog, not replace it. |

**Assumptions & limits:** inference is sampling-based; works best on self-describing payloads
(JSON/text); topic-level consumer discovery is automatic from broker metadata, field-level
observed lineage needs a thin read-only wrapper in the consumer; this is a young project —
not yet battle-tested at large scale.

## How it's built

~29k lines of Python, **1,600+ tests**, CI-enforced coverage and type-checking on new code.
Types are inferred by typed-frequency analysis and quorum voting with per-field
Wilson-interval confidence. All inference is deterministic by default — same input, same
result — and nothing leaves your network in offline mode. A reproducible eval harness scores
the system against hand-labelled benchmarks: on the bundled streams, schema F1 0.93, PII F1
0.86, 0% false positives on clean data, calibration error (ECE) ≈ 0.10 (deterministic path;
run `streamforge eval` to reproduce). Connectors (Kafka, SQS, IBM MQ) sit behind a
source-agnostic read interface, so the inference/mapping/drift engine never depends on the
transport.

## License

[Apache-2.0](LICENSE)
