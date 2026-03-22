#!/usr/bin/env bash
# ============================================================================
# demo/start.sh — Production-like StreamForge startup
# ============================================================================
#
# Starts all 4 event streams continuously, infers schema once, then
# runs drift monitoring until Ctrl+C.  All output goes to logs/.
#
# Usage:
#   bash demo/start.sh
#
# Monitor in another terminal:
#   tail -f logs/watch.log
#   tail -f logs/producer.log
#   tail -f logs/metrics.log
#
# Stop cleanly:
#   Ctrl+C  (the trap handler kills child processes)
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Load environment ──────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/.env"
    set +a
fi

BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
TOPIC="events.all"
LOG_DIR="${STREAMFORGE_LOG_DIR:-logs}"

mkdir -p "$LOG_DIR"

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"; GREEN="\033[32m"; CYAN="\033[36m"; RED="\033[31m"; DIM="\033[2m"; RESET="\033[0m"

info()  { echo -e "$(date -u +%H:%M:%SZ)  ${GREEN}▶${RESET}  $*"; }
error() { echo -e "$(date -u +%H:%M:%SZ)  ${RED}✗${RESET}  $*" >&2; }

# ── Process tracking ─────────────────────────────────────────────────────────
FEED_PID=""
WATCH_PID=""
KAFKA_METRICS_PID=""

cleanup() {
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "${ts}  shutdown  feed_pid=${FEED_PID} watch_pid=${WATCH_PID}" >> "$LOG_DIR/metrics.log" 2>/dev/null || true
    info "Shutting down…"
    [ -n "$KAFKA_METRICS_PID" ] && kill "$KAFKA_METRICS_PID" 2>/dev/null || true
    [ -n "$WATCH_PID" ]  && kill "$WATCH_PID"  2>/dev/null || true
    [ -n "$FEED_PID" ]   && kill "$FEED_PID"   2>/dev/null || true
    # Belt-and-suspenders: kill any lingering instances by name
    pkill -f "demo/feed_all.py"   2>/dev/null || true
    pkill -f "streamforge watch"  2>/dev/null || true
    wait 2>/dev/null || true
    info "All processes stopped.  Logs in: $LOG_DIR/"
}
trap cleanup EXIT

# ── Guards ───────────────────────────────────────────────────────────────────
API_KEY_VALUE="${GROQ_API_KEY:-${LLM_API_KEY:-${OPENAI_API_KEY:-}}}"
if [ -z "$API_KEY_VALUE" ] || [[ "$API_KEY_VALUE" == *"your_key_here"* ]]; then
    error "No LLM API key found. Set GROQ_API_KEY in demo/.env."
    exit 1
fi

# ── Verify Kafka is reachable ─────────────────────────────────────────────────
info "Checking Kafka connectivity…"
KAFKA_CONTAINER="kafka-streamforge-demo"
if ! docker inspect "$KAFKA_CONTAINER" &>/dev/null; then
    error "Kafka container '$KAFKA_CONTAINER' not running. Run: bash demo/setup.sh"
    exit 1
fi
if ! streamforge kafka-ping "$TOPIC" --brokers "$BROKERS" --timeout 10 2>/dev/null; then
    error "Kafka ping failed on $BROKERS/$TOPIC. Is Kafka healthy? Check: docker ps"
    exit 1
fi
info "Kafka OK — ${BOLD}$BROKERS${RESET} → ${BOLD}$TOPIC${RESET}"

# ── Remove stale output to ensure fresh inference ────────────────────────────
if [ -d "schemas/$TOPIC" ]; then
    info "Removing stale schemas/$TOPIC for fresh init…"
    rm -rf "schemas/$TOPIC"
fi
if [ -d "drift_reports/$TOPIC" ]; then
    info "Removing stale drift_reports/$TOPIC…"
    rm -rf "drift_reports/$TOPIC"
fi

# ── Log header ───────────────────────────────────────────────────────────────
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${CYAN}  StreamForge — Production Run${RESET}"
echo -e "${BOLD}${CYAN}  Started: $START_TS${RESET}"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${DIM}Logs → $LOG_DIR/${RESET}"
echo -e "  ${DIM}Monitor: tail -f $LOG_DIR/watch.log${RESET}"
echo ""

# ── STEP 1: Start continuous event producers ─────────────────────────────────
# Kill any stale producer from a previous run to avoid duplicate PIDs / inflated metrics
pkill -f "demo/feed_all.py" 2>/dev/null || true
info "Starting event producers (4 streams)…"
python3 "$SCRIPT_DIR/feed_all.py" \
    --brokers "$BROKERS" \
    --payment-rate 2 \
    --booking-rate 1 \
    --iot-rate 5 \
    --wiki-rate 1.5 \
    >> "$LOG_DIR/producer.log" 2>&1 &
FEED_PID=$!
echo "${START_TS}  startup  feed_pid=${FEED_PID}" >> "$LOG_DIR/metrics.log"
info "Producers running (PID $FEED_PID) → $LOG_DIR/producer.log"

# ── STEP 2: Wait for enough events to make init meaningful ───────────────────
# 45s at ~9.5 events/s gives ~425 events — enough that all 7 clusters exceed
# MIN_EVENTS_FOR_LLM_INFERENCE=50, unlocking full LLM inference for every cluster.
info "Waiting 45 s for events to accumulate…"
sleep 45

# Verify producers are still alive
if ! kill -0 "$FEED_PID" 2>/dev/null; then
    error "Producer exited unexpectedly. Check $LOG_DIR/producer.log"
    exit 1
fi

# ── STEP 3: Schema inference ─────────────────────────────────────────────────
info "Running schema inference (--sample-size 400)…"
streamforge init "kafka://$TOPIC" \
    --brokers "$BROKERS" \
    --sample-size 400 \
    --output schemas \
    > "$LOG_DIR/init.log" 2>&1
INIT_EXIT=$?
if [ $INIT_EXIT -ne 0 ]; then
    error "streamforge init failed (exit $INIT_EXIT). See $LOG_DIR/init.log"
    cat "$LOG_DIR/init.log" | tail -20
    exit 1
fi
info "Schema inference complete → $LOG_DIR/init.log"

# Show cluster summary
CLUSTER_COUNT=$(grep -c "cluster_id" schemas/"$TOPIC"/profile.yaml 2>/dev/null || echo "?")
info "Inferred ${BOLD}${CLUSTER_COUNT} sub-schemas${RESET} in schemas/$TOPIC/"

# ── STEP 4: Start continuous drift monitor ───────────────────────────────────
info "Starting drift monitor (30 s interval, 200-event sample)…"
streamforge watch "kafka://$TOPIC" \
    --brokers "$BROKERS" \
    --interval 30 \
    --sample-size 200 \
    >> "$LOG_DIR/watch.log" 2>&1 &
WATCH_PID=$!
info "Watch running (PID $WATCH_PID) → $LOG_DIR/watch.log"

# ── STEP 5: Background Kafka offset metrics ───────────────────────────────────
# Every 60 s, append total topic offset sum to metrics.log
kafka_metrics_loop() {
    while true; do
        sleep 60
        local ts
        ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        local offsets
        offsets=$(docker exec "$KAFKA_CONTAINER" \
            kafka-run-class kafka.tools.GetOffsetShell \
            --broker-list localhost:9092 \
            --topic "$TOPIC" --time -1 2>/dev/null \
            | awk -F: '{sum += $3} END {print sum}' || echo "unavailable")
        echo "${ts}  kafka_total_offset=${offsets}" >> "$LOG_DIR/metrics.log"
    done
}
kafka_metrics_loop &
KAFKA_METRICS_PID=$!

# ── STEP 6: Wait (block until Ctrl+C) ────────────────────────────────────────
echo ""
echo -e "  ${DIM}System running. Press Ctrl+C to stop.${RESET}"
echo -e "  ${DIM}Monitor drift: tail -f $LOG_DIR/watch.log${RESET}"
echo -e "  ${DIM}Kafka UI: http://localhost:8080${RESET}"
echo ""

# Wait for the watch process (if it exits early, something is wrong)
wait "$WATCH_PID"
WATCH_EXIT=$?
if [ $WATCH_EXIT -ne 0 ]; then
    error "streamforge watch exited with code $WATCH_EXIT. Check $LOG_DIR/watch.log"
fi
