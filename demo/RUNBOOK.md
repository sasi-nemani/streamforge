# StreamForge Demo Runbook

Two ways to demo, both driving **real `streamforge` CLI commands** (no mock output):

| Demo | Needs | Best for |
|---|---|---|
| **Offline** (`demo/offline_demo.sh`) | nothing — deterministic | rock-solid on-stage, reproducible |
| **Live LLM** (`demo/demo.sh`) | Kafka stack + `GROQ_API_KEY` | the "AI-native" wow (semantic types, enum detection) |

The recommended flow opens **offline** (safe, reproducible), then optionally shows the **live-LLM** enrichment as the encore.

---

## A. Offline demo (5 minutes, zero dependencies)

```bash
bash demo/offline_demo.sh
```

### Act 1 — Deterministic inference
```bash
streamforge init events/payments/stream_v1 --offline -o /tmp/demo
```
- **Narrate:** "No LLM, no API key. Types come from statistics; PII from deterministic rules. Run it again — byte-identical schema. That's reproducibility you can put in CI."
- Point out: PII flags (`user.email`, `user.name`, `metadata.ip_address`), and the **confidence** — it's a Wilson lower bound on type agreement, discounted for catch-all types, not a guess.

### Act 2 — Prove it works (the money slide)
```bash
streamforge eval payments       # and: streamforge eval bookings
```
- **Narrate:** "How do you know it's right? We score it against hand-labeled ground truth."
- Read the scorecard: schema **type F1 ≈ 0.93**, **PII F1 ≈ 0.86**, **drift F1 ≈ 0.83**, **FPR-null 0%**, **ECE ≈ 0.10 (well-calibrated)**.
- The one `✗ enum_add` is the honest hook: "the offline path has no enum baseline — that's exactly what the LLM layer adds." → segue to the encore.
- Export for the deck: `streamforge eval --json scorecard.json`.

### Act 3 — Detect, explain, block
```bash
streamforge plan events/payments/stream_v2_drift --schema /tmp/demo/stream_v1/schema.yaml
```
- **Narrate:** "Producer ships a change. We compare the new stream to the contract."
- 13 drifts found, incl. a **new `card_last_four` PII field**, a timestamp type change, removed fields.
- Open the drift report — every finding shows its **Evidence**: `chi-squared test, p<0.0001, effect size 0.88`. "Not a vibe — a hypothesis test, FDR-corrected across all fields."
- Exit code 1 + `Policy action: BLOCK` → "this is the CI gate that stops the breaking deploy."

---

## B. Live-LLM encore (semantic enrichment)

Prereq: `bash demo/setup.sh` then `export GROQ_API_KEY=...` (or `demo/.env`).

```bash
# Same init, but WITH the model — note semantic types the stats path can't see:
streamforge init events/payments/stream_v1 -o /tmp/demo-llm
# event_id -> uuid, timestamp -> timestamp_epoch_ms, user.email -> email
```
- **Narrate:** "Now the model enriches: it recognizes UUIDs, epoch timestamps, emails — the semantic types statistics alone can't infer. Type-accuracy and ECE both jump."
- **The determinism beat:** run the same `init` a second time →
  ```
  structural-fingerprint cache hit — skipping LLM
  ```
  "Identical shape ⇒ we never call the model again. First touch is AI-native; steady state is free and deterministic." Confirm with metrics: `schema_cache_hits_total` ticks up, `inference_llm_calls_total` does not.

The full Kafka-based 4-act investor script lives in `demo/demo.sh` (live events → infer → drift → CI gate).

---

## Talking points cheat-sheet
- **Measurable:** `streamforge eval` gives P/R/F1, detection latency, FPR-under-null, and calibration — the system grades itself against ground truth.
- **Explainable:** every drift carries its test, p-value, and effect size, in the report and the audit log.
- **Deterministic & cheap:** offline mode needs no model at all; with the model, the fingerprint cache means the LLM is consulted only on a novel shape.
- **Honest:** previously-silent failures are now counters (`parse_failures_total`, `inference_failures_total`, …) — the system tells you what it couldn't process.
