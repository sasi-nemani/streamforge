# HN Post Draft

## Title
Show HN: StreamForge — catches breaking Kafka schema changes before they deploy

## Body

We built a CLI that automatically learns what your Kafka event schemas look like,
then blocks breaking changes in CI before they reach production.

**The problem:** Producer teams change event formats without telling consumer teams.
There's no formal contract. Things break silently. Last month a fintech team spent
4 hours debugging a field rename that silently degraded their fraud model for 6 hours.

**How it works:**

```
# See your governance posture instantly
streamforge discover --brokers localhost:9092
→ "44 of your 47 Kafka topics have no schema contract"

# Learn the schema once ($0.02, never again)
streamforge init kafka://events.payments --brokers localhost:9092

# Watch continuously (pure statistics, $0/month forever)
streamforge watch kafka://events.payments --brokers localhost:9092

# Block in CI (GitHub Action, zero config)
uses: streamforge/streamforge-action@v1
```

**What makes it different:**
- LLM runs once to infer schema — monitoring is pure statistics ($0.00/cycle)
- Works with any Kafka-compatible broker (Confluent, Redpanda, MSK, local)
- Schema stored as YAML in your repo — diff-able in PRs, human-editable
- `streamforge demo` — try it with no Kafka or API key in 60 seconds

**What we're looking for:** 5 teams running Kafka who've had a schema incident
in the last 6 months. Free setup (we do it), 30-day trial. We want a quote if
it catches something.

GitHub: [link]
Demo (no Kafka needed): `pip install streamforge-cli && streamforge demo`

---

## Screenshots to capture (before posting)

1. `streamforge discover` — run against a Kafka with 10+ topics.
   Show the "X exposed / Y protected" panel.
   Caption: "The first command shows you the problem."

2. GitHub PR with red X status check from the StreamForge Action.
   Caption: "The PR that would have broken prod."

3. `streamforge demo` output — showing "🔴 BREAKING CHANGE CAUGHT".
   Caption: "Try it in 60 seconds — no Kafka needed."

4. `streamforge incident-report` — showing 1-2 incidents.
   Caption: "What your VP of Engineering sees after 30 days."

## When to post
After GitHub Action is published to Marketplace (for the zero-config CTA).
Post Tuesday or Wednesday, 9am US Eastern.
