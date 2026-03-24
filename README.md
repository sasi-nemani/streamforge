# StreamForge — CI Guardrail for Data Pipelines

> Like a type checker for your Kafka event streams. Catches breaking changes before they deploy.

## The problem in one sentence

Every team running Kafka is one silent field rename away from a production incident.
When a producer changes "amount" to "amount_minor_units" without telling anyone, fraud
models degrade, ledgers go off by 100x, and engineers lose hours debugging before
the root cause surfaces.

## How it works

- **Learn once** — one LLM call ($0.02) infers a typed schema from your live events
- **Watch free** — continuous statistical drift detection runs every 30 seconds, zero LLM cost
- **Block in CI** — `streamforge plan` exits 1 on breaking drift, blocking merges automatically

---

## 5-minute quickstart

### Prerequisites

- Python 3.11+
- Kafka running (or use the included demo: `bash demo/reset.sh`)
- Groq API key (free at [console.groq.com](https://console.groq.com))

### Install

```bash
pip install streamforge-cli
```

### See your governance posture

```bash
streamforge discover --brokers localhost:9092
# Output: Discovered 47 topics | Monitored (0) | Unmonitored (47)
# Every unmonitored topic is a schema incident waiting to happen.
```

### Infer your first schema

```bash
export GROQ_API_KEY=gsk_...
streamforge init kafka://events.payments --brokers localhost:9092
# Writes schemas/events.payments/schema.yaml — commit it to Git.
```

### Watch for drift

```bash
streamforge watch kafka://events.payments --brokers localhost:9092
# Polls every 30s. Alerts on breaking changes. Zero cost per cycle.
```

### Block drift in CI

```bash
streamforge plan kafka://events.payments --brokers <brokers>
# Exits 0 (clean) or 1 (breaking drift found) — plug into any CI pipeline.
```

---

## CI Integration (GitHub Action)

```yaml
- uses: streamforge/streamforge-action@v1
  with:
    brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
    topic: events.payments
    api-key: ${{ secrets.GROQ_API_KEY }}
```

PRs that introduce schema drift fail the status check and are blocked from merging.
See [streamforge-action/README.md](streamforge-action/README.md) for full configuration.

---

## Commands

| Command | What it does | When to use it |
|---------|-------------|----------------|
| `init` | Infer schema from event sample (LLM, one-time) | First time on a new topic |
| `watch` | Continuous drift monitoring loop | Always-on production monitoring |
| `plan` | One-shot drift check, exits 1 on breaking drift | CI/CD pipeline gate |
| `discover` | List all Kafka topics with governance status | Kickoff — see your exposure |
| `profile` | Multi-schema profiling for mixed-event-type streams | Topics with multiple event types |
| `report` | Print current schema and drift history | Debugging, auditing |
| `incident-report` | Structured summary of past drift incidents | Sharing with engineering managers |
| `export` | Convert schema to JSON Schema, Avro, Protobuf, Flink, ksqlDB | Downstream integration |
| `kafka-ping` | Connectivity check — exits 0 if reachable | Pre-flight checks, health probes |

---

## Architecture in one paragraph

StreamForge uses an LLM exactly once per stream to infer a typed schema from a sample
of real production events. After that, all drift detection is pure statistics: binomial
z-tests for presence rate changes, chi-squared tests for type distribution shifts, and
PSI for numeric field drift. The LLM cost is a one-time $0.02 bootstrapping fee. Every
subsequent monitoring cycle costs $0.00. Schemas are stored as human-readable YAML files,
committed to Git, and diff-able in pull requests — schema as code, not a proprietary registry.

---

## Design partner program

We are looking for 5 design partner companies — Series B+ fintechs or data-heavy
engineering teams running Kafka with 3+ producing teams who have had at least one
schema-related incident in the past 6 months.

Offer: free deployment (we handle setup in under 1 hour), 30-day trial on one Kafka
topic, no contract. In exchange: a monthly feedback call and a quote if value delivered.

Contact: [your email]

---

## License

MIT
