# StreamForge Pitch Memo

## One Line
StreamForge is schema contract infrastructure for event streams: it infers contracts from live payloads, stores them as code, and continuously detects drift before downstream systems break.

## The Problem
Modern event systems run on hidden contracts.

Producers change payloads.
Consumers assume fields, formats, and semantics remain stable.
When those assumptions break, teams usually find out late:

- pipelines fail after deploys
- dashboards silently degrade
- compliance teams discover new PII after it is already in motion
- root-cause analysis takes hours because no one owns the real contract

Existing tools do not solve this well:

- schema registries enforce schemas you already wrote
- data quality tools make engineers write rules manually
- warehouse observability products watch tables after the damage is already downstream

The result is a control-plane gap for event evolution.

## Our Thesis
Every event-driven company already has data contracts. They are just undocumented, inconsistent, and operationally invisible.

StreamForge turns those hidden contracts into explicit infrastructure:

1. infer the contract from real event payloads
2. declare the contract in Git as `schema.yaml`
3. detect drift continuously before consumers and compliance postures break

This is "Terraform for event schemas."

## Product
The MVP is intentionally narrow:

- `streamforge init <stream_path>`
  Infers the contract from real events and writes:
  - `schema.yaml`
  - `profile.yaml`
  - `inference_report.md`
  - `stream_policy.yaml`

- `streamforge plan <stream_path>`
  One-shot drift check for CI/CD. Exits non-zero on critical drift.

- `streamforge watch <stream_path>`
  Continuous drift monitoring against a rolling event window.

## Why It Works
The architecture separates cold-path intelligence from hot-path enforcement.

- Cold path:
  LLM-assisted schema inference during onboarding only
- Hot path:
  deterministic statistical drift detection with no LLM dependency
- Control plane:
  Git-native contract artifacts

This gives the product three properties buyers care about:

- fast onboarding
- deterministic runtime behavior
- auditable contract history

## Differentiation
StreamForge is not another quality dashboard.

- Versus Great Expectations / Soda:
  They require manual rule writing. StreamForge infers the contract first.
- Versus Monte Carlo / Bigeye:
  They monitor warehouse tables, not event streams at the point of change.
- Versus Schema Registry:
  It enforces schemas already authored by humans. It does not infer them or detect live drift against observed payloads.

The wedge is event contract inference plus operational drift detection.

## Why Now
Three forces make this timely:

- event-driven systems are now standard in product, platform, and ML pipelines
- downstream consumers have multiplied, making hidden contract changes more expensive
- LLMs are finally good enough to accelerate onboarding without sitting in the runtime path

## MVP Proof Points
Current MVP proof:

- infers schema contracts from included test streams
- ingests live public event streams via included taps for Wikipedia, Coinbase, and OpenSky
- flags PII during onboarding
- detects required-field removal, type drift, new fields, and new PII
- supports multi-schema streams
- uses rolling windows for watch mode instead of noisy single-poll deltas
- has a passing automated test suite

## What This Becomes
The MVP is the seed of a larger control plane:

- Kafka / PubSub / Kinesis connectors
- persisted watcher state and HA monitoring
- consumer impact analysis and blast radius
- schema promotion and review workflows
- policy-driven enforcement in CI and production

## Why This Is A Fundable Wedge
This starts as a narrow developer tool but expands into system-of-record infrastructure.

If a team adopts StreamForge for contract inference and drift blocking, it naturally becomes the place to manage:

- stream ownership
- consumer dependencies
- schema lifecycle
- PII governance
- deployment gates

That is a durable platform surface, not a one-off script.

## Demo Readout
There are two strong demo paths in the repo:

- Synthetic control-path demo:
  `streamforge demo`
- Live public stream demo:
  - `python3 taps/wikipedia.py --max 200`
  - `python3 taps/coinbase.py --max 200`
  - `python3 taps/opensky.py --max 300`
  - `streamforge init events/<source>/live`
  - `streamforge ui`

This lets us show both deterministic drift detection and source-agnostic real-world ingestion.

## Ask
We are raising to turn this from a proven MVP into a production-grade control plane for event contracts:

- connector hardening
- enterprise reliability features
- policy and workflow layer
- buyer-ready integrations

The goal is simple: make schema drift a managed infrastructure problem instead of a recurring incident class.
