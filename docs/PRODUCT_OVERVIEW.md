# StreamForge — Product Overview

---

## The Problem Nobody Has Solved

Every company running modern software has the same invisible crisis.

They use event streams — Kafka, Kinesis, SQS, Pub/Sub — to move data between services. A payments service publishes events. A fraud detection service reads them. A billing service reads them. A data warehouse ingests them. So does the ML team's feature pipeline.

Here is the problem: **nobody wrote down what those events are supposed to look like.**

The schema — the contract that says "this event has a field called `amount`, it's a number in dollars, it's always present" — lives in a developer's head. Maybe a Slack message from 2021. Maybe a Confluence page that hasn't been touched since the person who wrote it left the company.

Then a developer makes a change. They rename `amount` to `amount_minor_units` because the team decided to store cents instead of dollars. Or they add a new field. Or they change the timestamp format. They don't update the schema, because there is no schema to update. They deploy at 2am.

Three hours later, the fraud detection service is throwing null pointer exceptions. The billing service is producing wrong invoices. The ML pipeline has been silently ingesting corrupt data for six hours. The on-call engineer spends four hours tracing the blast radius back to a two-line code change.

This is not a rare edge case. At companies with more than 50 engineers and event-driven architecture, this happens weekly.

---

## Why Nothing Exists To Fix It

The tools that exist today were built for a different problem.

**Great Expectations and Soda** are data quality tools — but they require you to write the rules yourself. They assume you already know what your data should look like. When you don't know (which is always, at the start), they're useless.

**Monte Carlo and Bigeye** are data observability platforms — but they watch tables in data warehouses, not live event streams. By the time data reaches a warehouse, the damage is already done. They also cost $50,000+ per year and require months to implement.

**Confluent Schema Registry** manages Avro and Protobuf schemas for Kafka — but again, you have to write the schema yourself first. It enforces contracts you've already declared. It doesn't help you discover what the contract should be.

**Homegrown checks** — most engineering teams eventually write their own ad-hoc validators — work until the person who wrote them leaves, or until the stream evolves past what the checks expected.

The gap is precise: **there is no tool that starts from "I don't know what my schema is" and produces a contract from production data, then enforces it continuously.**

---

## What StreamForge Does

StreamForge is schema contract infrastructure for event streams. It does three things.

**1. Infer — discover the contract from production data**

Point StreamForge at a folder of events (or, soon, a live Kafka topic). It reads the data, discovers the event families — for example, a payments stream might have `payment_initiated`, `payment_completed`, and `payment_failed` events that each look different — and infers a precise schema for each one. Field types, presence rates, which fields are always there vs. sometimes there, which fields look like PII. It uses an LLM to make this inference fast and accurate. The whole process takes under 60 seconds for a 300-event sample.

**2. Declare — store the contract as code**

The output is a `schema.yaml` file. Human-readable. Git-committable. Reviewable in a pull request. This is the key insight: once schema is code, it gets all the benefits of code — version history, code review, rollback, CI/CD enforcement. Teams can see exactly when and why the schema changed, who approved it, and what the downstream impact was.

**3. Detect — catch drift before systems break**

StreamForge runs continuously against the live stream, comparing new events to the declared contract. It uses statistical tests — not brittle string comparisons — to detect meaningful change. When something drifts, it classifies the severity:

- **Tier 1** (non-breaking): a new optional field appeared. Log it, move on.
- **Tier 2** (breaking but fixable): the timestamp format changed from epoch to ISO8601. Alert the team, propose a correction.
- **Tier 3** (critical): a required field disappeared. A PII field appeared that wasn't in the contract. Block the deployment. Page someone.

In CI/CD, `streamforge plan` works like `terraform plan` — it shows you exactly what changed before you ship, and exits with an error code if critical drift is detected.

---

## The Enterprise Pain Points This Solves

**Data engineering teams** spend an estimated 20-30% of their time debugging pipelines that broke because an upstream producer changed their event format without telling anyone. StreamForge makes that change visible before it becomes an incident.

**Platform engineering teams** need to enforce contracts between hundreds of microservices. Right now they do it with documentation, code reviews, and prayer. StreamForge gives them a CI gate — the same way they already gate API changes with OpenAPI schema validation.

**Compliance and security teams** have no visibility into PII appearing in event streams. A developer adds a `card_last_four` field to debug a payment failure, forgets to remove it, and suddenly you have payment card data flowing into your logging pipeline. StreamForge detects new PII fields and flags them immediately.

**Data science and ML teams** onboarding to a new stream currently spend 2-4 weeks reading logs and asking Slack questions to understand what the data looks like. StreamForge gives them a `schema.yaml` and an inference report — field types, presence rates, sample values — in under a minute.

---

## Why This Is a Big Market

Every company with more than 30 engineers running microservices has this problem. The TAM is not "companies using Kafka" — it's "companies with internal data contracts they can't enforce." That is the entire enterprise software market.

The expansion path is clear. Today: infer and enforce contracts for a single stream. Next: Kafka connector, CI/CD integration, team-level consumer tracking (when stream X drifts, automatically notify every team whose service reads it). Later: schema promotion workflows, compliance audit trails, auto-remediation proposals.

The wedge is tight. The platform is large. And the category is empty.

---

## What We Have Built

A working MVP that runs today on any folder of NDJSON files — which is how we simulate Kafka without needing Kafka. The architecture is designed so the file reader can be swapped for a live Kafka consumer with zero changes to the inference or drift detection layers.

It handles messy real-world data: broken JSON, log-prefixed lines, mixed event types in the same stream. It discovers event families automatically. It detects PII without an API call. It runs the demo — infer schema, inject drift, catch it — in under two minutes.

The live data taps (Wikipedia edits, Coinbase market ticks, OpenSky flight telemetry) prove the engine is source-agnostic before Kafka is added. You can run them right now and watch StreamForge infer a schema from a live public stream in real time.

**The problem is real. The solution works. The category is ours to define.**
