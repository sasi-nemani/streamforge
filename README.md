# StreamForge

**Schema contract infrastructure for event streams.**

StreamForge reads your live event stream, infers a schema from production data, and continuously detects when it drifts — before downstream systems break. Schema as code, enforced automatically.

---

## Quickstart (3 commands)

```bash
# 1. Clone and install
git clone <repo> && cd streamforge-mvp && pip install -e .

# 2. Infer a schema from events
streamforge init events/payments/stream_v1

# 3. Detect drift
streamforge plan events/payments/stream_v2_drift \
  --schema schemas/stream_v1/schema.yaml
```

Requires a free [Groq API key](https://console.groq.com) (or any OpenAI-compatible endpoint).

---

## Investor Demo

The full live demo runs on local Kafka with Docker — no cloud dependencies.

```bash
# One-time setup (~2 min)
bash demo/setup.sh

# Run the demo (~5 min)
bash demo/demo.sh
```

**What it shows:**
1. 4 event types flowing through a single Kafka topic
2. Sub-schemas inferred per event type — with PII flagged automatically
3. A breaking change caught live within one poll cycle (~10 seconds)
4. A CI gate that exits non-zero and blocks a deploy

See [`demo/README.md`](demo/README.md) for full instructions.

---

## How it works

```
EVENT STREAM  →  init (LLM, runs once)  →  schema.yaml
                                              │
                     watch / plan  ←──────────┘
                   (statistical, no LLM, <5ms)
                         │
                   drift detected
                         │
                   report + CI gate
```

**Key properties:**
- LLM runs once at `init`. Drift detection is fully statistical — zero API cost in the monitoring hot path
- Schema is a plain YAML file — git-committable, diff-able in PRs, human-editable
- Pluggable connectors: swap the file reader for Kafka/SQS with no changes to inference or detection

---

## Requirements

- Python 3.11+
- Groq API key (free) — or OpenAI, Ollama, any OpenAI-compatible endpoint
- Docker — only for the Kafka demo; not required for file-based use
