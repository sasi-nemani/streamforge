# StreamForge Demo

Self-contained investor demo. Runs on local Kafka — no cloud dependencies.

**What it shows in ~5 minutes:**
1. 4 event types flowing through a single Kafka topic
2. Sub-schemas inferred automatically, PII flagged with zero config
3. A breaking schema change caught live within one poll cycle (~10 seconds)
4. A CI gate that exits non-zero and blocks a deploy

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker Desktop | Must be running |
| Python 3.11+ | `python3 --version` to verify |
| Groq API key | Free at [console.groq.com](https://console.groq.com) |

---

## Setup (one time, ~2 minutes)

```bash
# 1. Add your API key
cp demo/.env.template demo/.env
# Edit demo/.env — set GROQ_API_KEY

# 2. Start Kafka, install deps, seed events
bash demo/setup.sh
```

---

## Run the demo

```bash
source demo/.env
bash demo/demo.sh
```

Press **ENTER** to advance between acts. Narration cues are printed inline.

---

## Demo acts

| Act | What happens |
|-----|-------------|
| 1 — Live events | `kafka-ping` confirms events are flowing |
| 2 — Schema inference | `init` infers 4 sub-schemas; PII fields highlighted |
| 3 — Drift detection | `inject_drift.py` sends 50 breaking events; `watch` catches them in ~10s |
| 4 — CI gate | `plan` exits 1, blocking the deploy |

---

## Files

```
demo/
├── setup.sh             One-time setup
├── demo.sh              The 5-act demo
├── cleanup.sh           Tear down Docker and generated output
├── feed_all.py          Background producer (4 event types → events.all)
├── inject_drift.py      Sends 50 deterministically broken payment events
├── docker-compose.yml   Kafka + Kafka UI
└── .env.template        Copy to .env and fill in GROQ_API_KEY
```

Kafka UI is available at **http://localhost:8080** during the demo.

---

## Troubleshooting

**Kafka not starting**
```bash
docker logs kafka-streamforge-demo
lsof -i :9092   # check if port is in use
```

**No events received**
```bash
python3 demo/feed_all.py --preseed 200 --no-live
```

**Drift not detected in Act 3**
```bash
python3 demo/inject_drift.py --count 100
```

**API key not found**
```bash
echo $GROQ_API_KEY
source demo/.env
```

**Port 8080 conflict** — edit `demo/docker-compose.yml` and change `"8080:8080"` to `"8081:8080"`.

---

## Reset

```bash
bash demo/cleanup.sh
bash demo/setup.sh   # start fresh
```
