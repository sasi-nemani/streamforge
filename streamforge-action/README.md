# StreamForge Schema Drift Gate — GitHub Action

Block pull requests that introduce breaking Kafka schema drift before they merge.

## What it does

1. Reads your committed `schema.yaml` for the given Kafka topic
2. Samples recent events from the topic
3. Runs `streamforge plan` to detect breaking drift
4. Fails the status check (exit 1) if TIER 3 drift is found
5. Posts a drift summary as a PR comment (when `GITHUB_TOKEN` is set)

## Usage

```yaml
name: Schema Drift Gate

on:
  pull_request:
    branches: [main, staging]

jobs:
  schema-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: streamforge/streamforge-action@v1
        with:
          brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
          topic: events.payments
          api-key: ${{ secrets.GROQ_API_KEY }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `brokers` | yes | — | Kafka bootstrap servers (e.g. `localhost:9092`) |
| `topic` | yes | — | Kafka topic to check (e.g. `events.payments`) |
| `schema-dir` | no | `schemas` | Directory containing `schema.yaml` files |
| `api-key` | no | — | LLM API key (Groq/OpenAI) — only needed for first-time init |
| `min-tier` | no | `3` | Minimum drift tier that fails the check (1, 2, or 3) |

## Outputs

| Output | Description |
|--------|-------------|
| `drift-detected` | `true` if drift was detected, `false` otherwise |
| `highest-tier` | Highest drift tier found (`1`, `2`, `3`, or `none`) |
| `report-path` | Path to the drift report markdown file |

## Exit codes

- `0` — No drift detected, or no schema file found (first run)
- `1` — Breaking drift detected at or above `min-tier`

## First-time setup

If no `schema.yaml` exists yet, the action emits a warning and exits 0.
Run `streamforge init` locally first and commit the resulting `schemas/` directory:

```bash
export GROQ_API_KEY=gsk_...
streamforge init kafka://events.payments --brokers $KAFKA_BOOTSTRAP_SERVERS
git add schemas/
git commit -m "feat: add schema contract for events.payments"
git push
```

## Multiple topics

Use a matrix strategy to gate multiple topics in one job:

```yaml
strategy:
  matrix:
    topic: [events.payments, events.bookings, events.fraud]
steps:
  - uses: streamforge/streamforge-action@v1
    with:
      brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
      topic: ${{ matrix.topic }}
```

## Adjust sensitivity

Lower `min-tier` to block on any drift (including non-breaking changes):

```yaml
- uses: streamforge/streamforge-action@v1
  with:
    brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
    topic: events.payments
    min-tier: '2'   # block on TIER 2+ drift (type changes, new required fields)
```

## License

MIT — see repository root for full license text.
