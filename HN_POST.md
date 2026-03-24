# Show HN: StreamForge — catches breaking Kafka schema changes before they deploy

## HN Title (exact copy-paste)
Show HN: StreamForge – catches breaking Kafka schema changes before they deploy

## HN URL
https://github.com/nskq4b6gmv-rgb/streamforge-mvp

---

## Body (copy-paste into HN text box)

We got paged at 2am because a payments team renamed `amount` to `amount_minor_units` without telling anyone. The fraud model got `null` for 6 hours before someone noticed. Fix took 4 minutes. Finding it took 6 hours.

StreamForge prevents this. Run it against any Kafka cluster:

```
$ streamforge discover --brokers $KAFKA_BROKERS

 Topic                    Schema  Version
 ─────────────────────────────────────────
 analytics.clicks           —       —
 analytics.pageviews        —       —
 data.cdc.orders            —       —
 events.bookings            ✓     1.0.0
 events.payments            ✓     1.0.0
 fraud.alerts               —       —
 fraud.signals              —       —
 ml.predictions             —       —
 payments.refunds           —       —
 platform.alerts            —       —
 [+16 more]

 22 of your 26 Kafka topics have NO schema contract.
 Any producer change could silently break downstream consumers.
```

Most teams are flying blind on 80%+ of their topics. This is the first command. It takes 10 seconds.

**From there:**

```bash
# Step 1: Infer schema from live traffic (LLM, once, ~$0.02)
streamforge init kafka://events.payments --brokers $KAFKA_BROKERS
→ 13 fields, 95% confidence, PII flagged (email, name, ip_address)
→ Written: schemas/events.payments/schema.yaml

# Step 2: Commit it — schema is now code, lives in git
git add schemas/ && git commit -m "schema: init payments v1.0.0"

# Step 3: Block breaking changes in CI (2 lines)
- uses: streamforge/streamforge-action@v1
  with:
    brokers: ${{ secrets.KAFKA_BOOTSTRAP_SERVERS }}
```

After init, **monitoring is pure statistics — no LLM, no API calls, $0/month**. The z-test runs on field presence rates and type distributions each cycle.

When a breaking change is detected, the PR is blocked:

```
[TIER 3] amount — field removed (was 98% present, now 0%)        ← PR blocked ❌
[TIER 3] card_last_four — new PII field detected (card_number)   ← PR blocked ❌
[TIER 2] timestamp — format changed: epoch_ms → ISO8601          ← PR warned ⚠️
[TIER 1] merchant_id — new optional field added                  ← silent ✓
```

**What makes it different from Confluent Schema Registry:**
- No Avro/Protobuf migration — works with existing JSON events, zero producer changes
- Schema lives in Git — PRs, diffs, rollbacks, code review
- `discover` shows your full governance posture in 10 seconds
- Works with any Kafka broker (MSK, Redpanda, Confluent Cloud, local)

**Try it now (no Kafka needed):**
```bash
pip install git+https://github.com/nskq4b6gmv-rgb/streamforge-mvp.git
streamforge demo
```

Looking for 5 teams running Kafka who've had a schema incident in the last 6 months. We'll do the setup, free for 30 days. If it catches something real we want a quote.

---

## Screenshots to capture before posting

### Screenshot 1 — The hook (terminal, dark theme)
Run:
```bash
streamforge discover --brokers localhost:9092
```
Caption: "The first command shows you the problem."
What to show: The full table with 22 unmonitored vs 4 monitored. The red summary box.

### Screenshot 2 — PR blocked
Show a GitHub PR with:
- Red X status check: "StreamForge Schema Guard — events.payments"
- The drift comment posted automatically showing Tier 3 drift
Caption: "The PR that would have broken prod."

### Screenshot 3 — The plan output
Run against stream_v2_drift (simulated breaking change):
```bash
streamforge plan events/payments/stream_v2_drift --schema schemas/stream_v1/schema.yaml
```
Caption: "Caught before it deployed."

### Screenshot 4 — GitHub Action green
Show a green CI check on a clean PR.
Caption: "Zero-config protection for every PR."

---

## Timing
Post Tuesday or Wednesday 9am US Eastern (peak HN traffic).

## Comment responses (have these ready)

**"How is this different from Schema Registry?"**
Registry enforces at write time with Avro/Protobuf — requires producer changes and migration. StreamForge infers schemas retroactively from existing JSON traffic. Schema lives in your repo, not an external service. Works in parallel with Registry if you have one.

**"What's the LLM cost?"**
~$0.02 per topic at Groq's free tier (or any OpenAI-compatible API). After init, zero API calls ever again — pure statistics.

**"False positive rate?"**
Binomial z-test, p<0.05 by default. For messy streams (IoT with 6 sensor sub-types) we use structural fingerprinting. Configurable thresholds per topic in `config/topics/*.yaml`.

**"Does it work with Avro?"**
Not yet — JSON only in the MVP. Avro deserialization on the roadmap.

**"What about schema evolution?"**
Tier 1 (new optional field) and Tier 2 (type widened, enum expanded) are non-blocking by default. Only Tier 3 (field removed, type narrowed, new PII) blocks. You configure this per-topic.
