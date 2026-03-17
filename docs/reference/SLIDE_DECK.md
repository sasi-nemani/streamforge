# StreamForge Slide Deck

## Slide 1 — Title
**StreamForge**

Schema contract infrastructure for event streams

Infer contracts from live payloads, store them as code, detect drift before downstream systems break.

---

## Slide 2 — The Problem
**Event systems run on hidden contracts**

- Producers evolve payloads without coordinated downstream review
- Consumers silently assume fields, formats, and semantics remain stable
- Drift is discovered late, after failures or bad data propagation
- New PII can enter production unnoticed

**Result:** recurring incidents, broken pipelines, and compliance risk

---

## Slide 3 — Why Current Tools Miss It
**The stack has a control-plane gap**

- Schema Registry: enforces schemas already written by humans
- Great Expectations / Soda: manual rules, not inferred contracts
- Monte Carlo / Bigeye: observe warehouse tables after the event layer
- Homegrown checks: brittle, undocumented, and person-dependent

**No tool turns real event payloads into a living, enforced contract**

---

## Slide 4 — Our Thesis
**Every event-driven company already has contracts**

They are just:

- implicit
- stale
- spread across teams
- operationally invisible

**StreamForge makes them explicit**

Infer → Declare → Detect

---

## Slide 5 — Product
**StreamForge = Terraform for event schemas**

1. `init`
   Infer a schema contract from live payloads
2. `plan`
   Check drift in CI before a deploy lands
3. `watch`
   Continuously monitor production for drift and new PII

Artifacts:

- `schema.yaml`
- `profile.yaml`
- `inference_report.md`
- `drift_reports/...`

---

## Slide 6 — Demo Story
**What the MVP proves**

- infer the payments stream contract from real events
- flag PII fields during onboarding
- detect:
  - required field removal
  - renamed/new field
  - timestamp format drift
  - new PII field
- block Tier 3 drift in CI
- ingest live public streams from Wikipedia, Coinbase, and OpenSky to show source-agnostic coverage

**This is an operational workflow, not just a dashboard**

---

## Slide 7 — Architecture
**Cold path AI, hot path determinism**

- LLM only at onboarding to accelerate contract inference
- deterministic drift detection in runtime monitoring
- rolling event windows for statistically meaningful comparisons
- multi-schema support for heterogeneous streams
- Git-native artifacts for review and audit

Message:

**AI helps create the contract. AI does not sit in the enforcement path.**

---

## Slide 8 — Why We Win
**Differentiation**

- No manual rule-writing to get started
- Event streams first, not warehouse-first
- Git-native contract workflow
- Built-in PII discovery
- Broker-agnostic architecture
- Live public taps already included for editorial, financial, and telemetry data

**Closest alternative today:** glue together schema registry, custom rules, and observability tooling by hand

---

## Slide 9 — Market Entry
**Initial buyer**

- platform engineering
- data engineering
- teams operating Kafka, Pub/Sub, SQS, or log-based event systems

**Initial wedge**

- onboarding undocumented streams
- drift detection in CI and production
- schema review in pull requests

---

## Slide 10 — Expansion Path
**From narrow wedge to control plane**

- managed connectors
- persisted watcher state and HA
- consumer impact / blast radius
- schema promotion workflows
- policy enforcement
- audit and compliance layer

This expands from a useful CLI into a system-of-record for event contracts.

---

## Slide 11 — Why Now
**Three tailwinds**

- event-driven architectures are everywhere
- hidden contracts are more expensive as consumer count grows
- LLMs are finally good enough to accelerate onboarding without owning production enforcement

---

## Slide 12 — Ask
**What this round funds**

- production hardening
- enterprise connectors
- reliability and policy layer
- design-partner pilots

**Goal:** make schema drift a managed infrastructure problem, not a recurring incident class
