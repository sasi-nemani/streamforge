#!/usr/bin/env bash
# ============================================================================
# StreamForge Investor Demo — ~5 minutes
# ============================================================================
#
# PRE-REQUISITES (run once before this script):
#   bash demo/setup.sh
#   source demo/.env   (or set GROQ_API_KEY in your shell)
#
# WHAT THIS SCRIPT DOES:
#   Act 1 — Show live events flowing through the merged Kafka topic
#   Act 2 — Infer sub-schemas (one per event type) with PII detection
#   Act 3 — Inject drift + watch it get detected live
#   Act 4 — CI gate: streamforge plan exits 1, blocking a deploy
#
# NARRATION GUIDE:
#   Lines beginning with "# NARRATOR:" are your speaking cues.
#   Press ENTER to advance between acts.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Load environment ────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/.env"
    set +a
fi

BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
TOPIC="events.all"
SCHEMA_PATH="schemas/$TOPIC/schema.yaml"

# ── Colours ─────────────────────────────────────────────────────────────────────
BOLD="\033[1m"
CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
DIM="\033[2m"
RESET="\033[0m"

header() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo ""
}

narrator() {
    echo -e "${DIM}┌─ NARRATOR ──────────────────────────────────────────┐${RESET}"
    # Word-wrap at ~54 chars with indent
    echo "$*" | fold -s -w 54 | while IFS= read -r line; do
        echo -e "${DIM}│  $line${RESET}"
    done
    echo -e "${DIM}└─────────────────────────────────────────────────────┘${RESET}"
    echo ""
}

pause() {
    echo ""
    echo -e "${DIM}  [Press ENTER to continue]${RESET}"
    read -r
}

# ── Guards ───────────────────────────────────────────────────────────────────────
API_KEY_VALUE="${GROQ_API_KEY:-${LLM_API_KEY:-${OPENAI_API_KEY:-}}}"
if [ -z "$API_KEY_VALUE" ] || [[ "$API_KEY_VALUE" == *"your_key_here"* ]]; then
    echo -e "${RED}✗ ERROR: No LLM API key found.${RESET}"
    echo "  Set GROQ_API_KEY in demo/.env and run:"
    echo "    source demo/.env && bash demo/demo.sh"
    exit 1
fi

# ── Clean state ───────────────────────────────────────────────────────────────────
rm -rf "schemas/$TOPIC" "drift_reports/$TOPIC"

# ── Reset Kafka topic for a fresh, deterministic demo run ─────────────────────────
# Running demo.sh multiple times without cleanup accumulates events from prior runs:
#   • Drifted events (from inject_drift.py) contaminate the topic
#   • The inference in Act 2 samples from this mixed data and produces a schema
#     that disagrees with fresh clean events — causing false-positive drift in
#     Act 3 before injection
#   • The streamforge-watcher consumer group commits offsets pointing at old data;
#     on the next run it resumes from those stale positions and replays drifted
#     events immediately on connect, flooding the screen with spurious alerts
#
# Deleting + recreating the topic is the only operation that atomically:
#   (a) removes all accumulated event data from prior runs
#   (b) resets all consumer group committed offsets (the group meta for a deleted
#       topic is dropped by the broker automatically)
#
# setup.sh is safe to re-run if you want a full reset; this inline reset is a
# lightweight guard that makes every demo.sh invocation idempotent.
KAFKA_CONTAINER="kafka-streamforge-demo"
if docker inspect "$KAFKA_CONTAINER" &>/dev/null 2>&1; then
    docker exec "$KAFKA_CONTAINER" \
        kafka-topics --bootstrap-server localhost:9092 \
        --delete --topic events.all 2>/dev/null || true
    sleep 2   # allow broker to finish partition cleanup before recreating
    docker exec "$KAFKA_CONTAINER" \
        kafka-topics --bootstrap-server localhost:9092 \
        --create --topic events.all --partitions 4 --replication-factor 1 \
        --if-not-exists 2>/dev/null
    python3 "$SCRIPT_DIR/feed_all.py" \
        --brokers "$BROKERS" \
        --preseed 500 \
        --no-live
fi

# ── Start live producer in background ─────────────────────────────────────────────
# Runs throughout Acts 1-3 so new events keep flowing
python3 "$SCRIPT_DIR/feed_all.py" \
    --brokers "$BROKERS" \
    --payment-rate 2 \
    --booking-rate 1 \
    --iot-rate 5 \
    --wiki-rate 1.5 \
    >/tmp/feed_all.log 2>&1 &
FEED_PID=$!

# Give producer a moment to connect and start publishing
sleep 3

# ── Cleanup on exit (Ctrl+C or end of script) ──────────────────────────────────────
cleanup() {
    kill "$FEED_PID" 2>/dev/null || true
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$FEED_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
}
trap cleanup EXIT

# ══════════════════════════════════════════════════════════════
header "ACT 1 OF 4 — Live Event Streams"
# ══════════════════════════════════════════════════════════════

narrator "Most companies have no idea what's actually \
flowing through their event buses. Kafka topics are \
black boxes — JSON with no contract, no PII inventory, \
no schema documentation. StreamForge fixes this with \
one command."

echo -e "  Right now, events from 4 source domains are flowing into a single merged topic:"
echo ""
echo -e "    ${CYAN}payment${RESET}         → payment transactions (PII: email)"
echo -e "    ${CYAN}booking${RESET}         → flight bookings (PII: passport, DOB, loyalty)"
echo -e "    ${CYAN}iot_sensor${RESET}      → 6 sensor types, mixed schema"
echo -e "    ${CYAN}wikipedia_edit${RESET}  → edit events, optional fields"
echo ""
echo -e "  Let's confirm events are flowing:"
echo ""

streamforge kafka-ping "$TOPIC" --brokers "$BROKERS"

echo ""
echo -e "  ${DIM}Browse live at: http://localhost:8080${RESET}"

pause

# ══════════════════════════════════════════════════════════════
header "ACT 2 OF 4 — Sub-Schema Inference"
# ══════════════════════════════════════════════════════════════

narrator "StreamForge reads from the Kafka topic, discovers \
that there are 4 different event types mixed together, \
and infers a separate schema for each — with type \
detection, PII flagging, confidence scores, and \
field-level documentation. Watch the output."

echo -e "  Running: ${BOLD}streamforge init kafka://$TOPIC${RESET}"
echo ""

streamforge init "kafka://$TOPIC" \
    --brokers "$BROKERS" \
    --sample-size 400 \
    --output schemas

echo ""
narrator "Notice the PII flags — passport numbers, emails, \
dates of birth, loyalty numbers. All detected \
automatically. No manual annotation. No config. \
The output is plain YAML — git-committable, \
human-readable, reviewable in a pull request."

echo ""
echo -e "  Primary schema: ${GREEN}$SCHEMA_PATH${RESET}  ${DIM}(largest cluster — iot_sensor)${RESET}"
echo -e "  Full profile:   ${GREEN}schemas/$TOPIC/profile.yaml${RESET}  ${DIM}(all sub-schemas)${RESET}"
echo -e "  ${DIM}Cat the YAML or inspect at: http://localhost:8080${RESET}"

# P2 fix: surface the inference report — it shows the PII/confidence summary
# that the narrator is talking about, but was previously written silently.
if [ -f "schemas/$TOPIC/profile_report.md" ]; then
    echo ""
    echo -e "  ${DIM}PII + confidence report:${RESET}"
    grep -E "^\|" "schemas/$TOPIC/profile_report.md" 2>/dev/null | head -8 || true
fi

pause

# ══════════════════════════════════════════════════════════════
header "ACT 3 OF 4 — Live Drift Detection"
# ══════════════════════════════════════════════════════════════

narrator "Now let's simulate what happens at 2am when a \
backend team deploys a breaking change. They rename \
'amount' to 'amount_minor_units', switch the timestamp \
format from epoch ms to ISO8601, and accidentally expose \
card numbers. Watch StreamForge catch it in real-time."

echo -e "  Starting drift monitor (polling every 5 seconds)..."
echo ""

# P0 fix: stop the live producer before starting the watch.
# With the producer running, live IoT events with stochastic field variations
# (debug.*, optional sensor fields) land in the watch window and trigger
# false-positive drift on the very first poll — before inject_drift.py runs.
# Stopping it here makes the topic static: the watch runs against the clean
# pre-seeded events and gets confirmed "clean" ticks. inject_drift.py then
# becomes the sole source of new events, so the drift story is unambiguous.
#
# The producer is restarted implicitly by pkill/cleanup on EXIT if needed.
# Use pkill rather than kill $FEED_PID to also catch any lingering instances
# from previous runs that slipped past cleanup.
pkill -f "demo/feed_all.py" 2>/dev/null || true
sleep 1  # allow in-flight Kafka sends to flush before watch starts

# Start watch in background — capture output to terminal AND log
WATCH_PID=""
streamforge watch "kafka://$TOPIC" \
    --brokers "$BROKERS" \
    --interval 5 \
    --sample-size 200 &
WATCH_PID=$!

# Give the consumer 2 s to join the group and subscribe at the latest offset
# BEFORE the clean seed burst arrives.  If we seed immediately, events can land
# before the consumer has joined and will be missed (offset already advanced).
sleep 2

# Seed 150 clean events across all 4 domains.  Two purposes:
#   1. Fills the watch window so the first poll shows ✓ clean ticks (not "○ warming up").
#      auto_offset_reset=latest means the window is empty until new events arrive.
#   2. Keeps iot_sensor/booking/wikipedia events in the window alongside the
#      50 drifted payment events, so non-payment clusters never drop to 0.
#      Without this, cluster_routing_regression fires for those clusters —
#      a false-positive that obscures the real payment drift story.
python3 "$SCRIPT_DIR/feed_all.py" \
    --brokers "$BROKERS" \
    --preseed 150 \
    --no-live

# Wait for 2-3 clean poll cycles (~5 s each) so investors see "✓ all clusters clean"
sleep 15

echo ""
echo -e "  ${YELLOW}>>> Injecting 50 drifted payment events...${RESET}"
echo -e "  ${DIM}(amount→amount_minor_units, timestamp format change, new card_last_four PII)${RESET}"
echo ""

python3 "$SCRIPT_DIR/inject_drift.py" \
    --brokers "$BROKERS" \
    --count 50

# Wait for next watch poll cycle to detect drift (interval=5s, give 2 cycles = 12s)
echo ""
echo -e "  ${DIM}Waiting for next poll cycle...${RESET}"
sleep 13

# Stop watch
kill "$WATCH_PID" 2>/dev/null || true
wait "$WATCH_PID" 2>/dev/null || true
WATCH_PID=""

echo ""
narrator "StreamForge caught the breaking change before \
any downstream consumer was affected. The drift \
report is already written to disk."

if ls "drift_reports/$TOPIC/"*.md 2>/dev/null | head -1 | grep -q .; then
    REPORT=$(ls "drift_reports/$TOPIC/"*.md 2>/dev/null | sort | tail -1)
    echo ""
    echo -e "  ${DIM}Drift report: $REPORT${RESET}"
fi

echo ""
narrator "Every accepted drift bumps the schema version \
and archives the old one. Here is the full history."

echo ""
streamforge report "kafka://$TOPIC" --output schemas

pause

# ══════════════════════════════════════════════════════════════
header "ACT 4 OF 4 — CI/CD Gate"
# ══════════════════════════════════════════════════════════════

narrator "StreamForge integrates into CI/CD as a gate. The \
'plan' command works like 'terraform plan' — it checks \
the current stream against the declared schema and exits \
non-zero if there are breaking changes. No breaking \
schema change ships without review."

echo -e "  Running: ${BOLD}streamforge plan kafka://$TOPIC --schema $SCHEMA_PATH${RESET}"
echo ""

set +e
streamforge plan "kafka://$TOPIC" \
    --brokers "$BROKERS" \
    --schema "$SCHEMA_PATH" \
    --sample-size 300
PLAN_EXIT=$?
set -e

echo ""
if [ "$PLAN_EXIT" -ne 0 ]; then
    echo -e "  ${RED}${BOLD}→ Exit code $PLAN_EXIT — pipeline BLOCKED${RESET}"
    echo -e "  ${DIM}In a real CI/CD pipeline, this step fails the build.${RESET}"
    echo -e "  ${DIM}No incompatible schema change ships without human sign-off.${RESET}"
else
    echo -e "  ${GREEN}→ Exit code 0 — schema is clean, pipeline proceeds.${RESET}"
fi

pause

# ══════════════════════════════════════════════════════════════
header "Summary"
# ══════════════════════════════════════════════════════════════

echo -e "  What you just saw in under 5 minutes:"
echo ""
echo -e "    ${GREEN}1.${RESET} ${BOLD}Sub-schema inference${RESET} from a heterogeneous Kafka topic"
echo -e "       Multiple sub-schemas auto-discovered per event_type"
echo ""
echo -e "    ${GREEN}2.${RESET} ${BOLD}Automatic PII detection${RESET}"
echo -e "       Passport numbers, emails, card numbers — zero config"
echo ""
echo -e "    ${GREEN}3.${RESET} ${BOLD}Live drift detection${RESET}"
echo -e "       Breaking change caught within one poll cycle (~5-10 seconds)"
echo ""
echo -e "    ${GREEN}4.${RESET} ${BOLD}CI/CD gate${RESET}"
echo -e "       Non-zero exit code blocks incompatible deploys"
echo ""
echo -e "  ${DIM}Architecture: pluggable connectors (Kafka, GCP Pub/Sub, AWS Kinesis, NDJSON files)${RESET}"
echo -e "  ${DIM}Output: git-committable YAML schemas — diff in PRs, track history in git${RESET}"
echo -e "  ${DIM}LLM: works with Groq (free), OpenAI, Ollama (local), any OpenAI-compatible API${RESET}"
echo ""
echo -e "  Resources:"
echo -e "    Kafka UI:       ${BOLD}http://localhost:8080${RESET}"
echo -e "    Schema output:  ${BOLD}schemas/$TOPIC/${RESET}"
echo -e "    Drift reports:  ${BOLD}drift_reports/$TOPIC/${RESET}"
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}${BOLD}  Demo complete.${RESET}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
