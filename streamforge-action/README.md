# StreamForge Schema Drift Gate — GitHub Action

> Block pull requests that introduce breaking Kafka schema changes before they merge.
> Like a type checker — but for your event streams.

---

## The problem this solves

```
$ streamforge discover --brokers $KAFKA_BROKERS

  22 of your 26 Kafka topics have NO schema contract.
  Any producer change could silently break downstream consumers.

  ✓ Monitored (4):    events.bookings, events.iot, events.payments, events.wiki
  ○ Unmonitored (22): analytics.clicks, analytics.pageviews, fraud.alerts [+19 more]

  Fix: streamforge init kafka://analytics.clicks --brokers $KAFKA_BROKERS
```

---

## Zero-config usage (2 lines in your workflow)

```yaml
# .github/workflows/schema-guard.yml
name: Schema Guard

on:
  pull_request:
    paths: ['events/**', 'schemas/**']

jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: streamforge/streamforge-action@v1
        with:
          brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
          api-key: ${{ secrets.GROQ_API_KEY }}   # free at console.groq.com
```

That's it. StreamForge reads your committed `schemas/` files and blocks any PR that introduces a Tier 3 (critical) schema change.

---

## What it blocks

| Change | Tier | Blocked by default? |
|--------|------|---------------------|
| Required field removed | **3 — Critical** | ✅ Yes |
| New PII field detected | **3 — Critical** | ✅ Yes |
| Type changed (string→int) | **3 — Critical** | ✅ Yes |
| Type widened (int→float) | 2 — Breaking | ❌ (warned in PR comment) |
| New optional field added | 1 — Trivial | ❌ (silent) |

---

## Full inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `brokers` | **yes** | — | Kafka bootstrap servers (`host:port`) |
| `topic` | no | auto | Topic to check. Auto-discovers from `schemas/` if omitted. |
| `schema-dir` | no | `schemas` | Directory containing committed `schema.yaml` files |
| `api-key` | no | — | Groq/OpenAI key. Only needed for first `init`, not ongoing monitoring. |
| `min-tier` | no | `3` | Tier at which to fail: `1` (any drift), `2` (breaking), `3` (critical only) |

## Outputs

| Output | Description |
|--------|-------------|
| `drift-detected` | `"true"` if drift above `min-tier` was found |
| `highest-tier` | `"1"`, `"2"`, `"3"`, or `"none"` |
| `report-path` | Path to the generated drift report `.md` file |

---

## First-time setup (one-off, ~2 min)

```bash
# 1. Install StreamForge CLI locally
pip install git+https://github.com/nskq4b6gmv-rgb/streamforge-mvp.git

# 2. Discover which topics need schemas
streamforge discover --brokers $KAFKA_BROKERS

# 3. Infer and commit schemas for your key topics (LLM does the work, ~$0.02)
streamforge init kafka://events.payments --brokers $KAFKA_BROKERS
git add schemas/events.payments/schema.yaml
git commit -m "schema: init events.payments v1.0.0"
git push

# 4. Add the GitHub Action — it now has a schema to guard against
```

After step 3, every future PR that touches `events/**` or `schemas/**` is automatically checked.

---

## Example PR comment (when drift is detected)

> **⚠️ StreamForge: Breaking Change Detected on `events.payments`**
>
> ```
> [TIER 3] amount — field removed (was 98% present, now 0%)
> [TIER 3] card_last_four — new PII field detected (card_number)
> [TIER 2] timestamp — format changed: epoch_ms → ISO8601 (100% of events)
> ```
>
> *Run `streamforge plan kafka://events.payments` locally to investigate.*

---

## How it works

```
Your repo                    GitHub Actions CI
────────────────             ────────────────────────────────────────
schemas/
  events.payments/           streamforge plan kafka://events.payments
    schema.yaml   ────────►    --schema schemas/events.payments/schema.yaml
    profile.yaml               ↓
                             Tier 3 drift? → exit 1 → PR blocked ❌
                             Tier 2 drift? → exit 0 → PR commented ⚠
                             No drift?     → exit 0 → ✓ green ✅
```

The `schema.yaml` is the contract. It lives in your repo, gets reviewed in PRs like any
other code, and is the single source of truth — no external schema registry required.

---

## Related CLI commands

```bash
# Learn the schema from live traffic (LLM inference, one-time, ~$0.02)
streamforge init kafka://events.payments --brokers $KAFKA_BROKERS

# Watch continuously (pure statistics, $0/month forever after init)
streamforge watch kafka://events.payments --brokers $KAFKA_BROKERS

# One-shot drift check (same logic as this Action)
streamforge plan kafka://events.payments --brokers $KAFKA_BROKERS

# See governance posture across your entire cluster
streamforge discover --brokers $KAFKA_BROKERS
```

---

## License

Apache 2.0.
