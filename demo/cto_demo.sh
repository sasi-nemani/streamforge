#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  StreamForge — CTO Demo                                          ║
# ║  One script. 90 seconds. Four real streams.                       ║
# ║                                                                   ║
# ║  Usage:  bash demo/cto_demo.sh                                    ║
# ║  Prereq: pip install -e .                                         ║
# ╚═══════════════════════════════════════════════════════════════════╝
set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EVENTS_DIR="$(cd "$PROJECT_DIR/../home/claude/streamforge-mvp/events" 2>/dev/null && pwd)" || \
EVENTS_DIR="$PROJECT_DIR/events"

cd "$PROJECT_DIR"

# ── Colors ────────────────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
CYAN='\033[36m'
RED='\033[31m'
YELLOW='\033[33m'
RESET='\033[0m'

# Clean previous runs
rm -rf schemas/ drift_reports/ .streamforge/ 2>/dev/null || true

pause() {
    echo ""
    echo -e "${DIM}  ▸ press enter to continue${RESET}"
    read -r
}

# ═══════════════════════════════════════════════════════════════════════
# ACT 1: "One command. Here's your schema."
# ═══════════════════════════════════════════════════════════════════════
clear
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  StreamForge${RESET}"
echo -e "${DIM}  Schema inference and drift detection for event streams${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  You have ${BOLD}four Kafka topics${RESET}. Thousands of events."
echo -e "  No Avro. No Protobuf. Just JSON flying through the pipe."
echo ""
echo -e "  ${DIM}What's the schema? Who knows.${RESET}"
echo ""
echo -e "  ${BOLD}One command:${RESET}"
echo ""
echo -e "    ${CYAN}streamforge profile events/payments/stream_v1${RESET}"
echo ""
pause

# Run profile (no LLM needed — instant)
echo -e "${BOLD}  Running...${RESET}"
echo ""
streamforge profile "$EVENTS_DIR/payments/stream_v1" --sample-size 200
echo ""
pause

# ═══════════════════════════════════════════════════════════════════════
# ACT 2: "Now let's see all four streams."
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${BOLD}Four streams. Four seconds.${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

for STREAM in payments/stream_v1 flights/stream bookings/stream iot/stream; do
    NAME=$(echo "$STREAM" | tr '/' '.')
    echo -e "  ${CYAN}▸ $NAME${RESET}"
    streamforge profile "$EVENTS_DIR/$STREAM" --sample-size 50 2>&1 | grep -E "sub-schema|Single|events from|Ingest Quality" | head -3 | sed 's/^/    /'
    echo ""
done

echo -e "  ${GREEN}✓ All four streams profiled. Zero API calls. Zero config.${RESET}"
echo ""
pause

# ═══════════════════════════════════════════════════════════════════════
# ACT 3: "Something breaks. We catch it."
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${BOLD}Now the real demo.${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${BOLD}streamforge demo${RESET}"
echo ""
echo -e "  ${DIM}A payments team deploys at 2:17am.${RESET}"
echo -e "  ${DIM}They rename 'amount' to 'amount_minor_units'.${RESET}"
echo -e "  ${DIM}They change the timestamp format.${RESET}"
echo -e "  ${DIM}And they accidentally start logging credit card digits.${RESET}"
echo ""
pause

streamforge demo --no-report

# ═══════════════════════════════════════════════════════════════════════
# ACT 4: "This is your CI gate."
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${BOLD}The CI gate.${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  In your CI pipeline, one line:"
echo ""
echo -e "    ${CYAN}streamforge plan events/payments/stream_v2_drift \\${RESET}"
echo -e "    ${CYAN}  --schema schemas/payments.demo/schema.yaml${RESET}"
echo ""
echo -e "  ${DIM}If it exits 0, merge. If it exits 1, block.${RESET}"
echo ""
pause

echo -e "${BOLD}  Running...${RESET}"
echo ""
# plan will exit 1 on Tier 3 — capture it
set +e
streamforge plan "$EVENTS_DIR/payments/stream_v2_drift" \
    --schema schemas/payments.demo/schema.yaml \
    --sample-size 100
EXIT_CODE=$?
set -e

echo ""
echo -e "  Exit code: ${RED}${EXIT_CODE}${RESET}"
echo ""

if [ "$EXIT_CODE" -eq 1 ]; then
    echo -e "  ${RED}✗ Deployment blocked.${RESET} The schema change breaks consumers."
    echo -e "  ${GREEN}✓ Your fraud model didn't get nulls for 6 hours.${RESET}"
else
    echo -e "  ${GREEN}✓ Clean. Safe to deploy.${RESET}"
fi

# ═══════════════════════════════════════════════════════════════════════
# CLOSE
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${BOLD}StreamForge${RESET}"
echo ""
echo -e "  Schema inference:   ${GREEN}\$0.02 per topic${RESET} (one LLM call)"
echo -e "  Continuous watch:   ${GREEN}\$0/month${RESET} (pure statistics, no API)"
echo -e "  Time to first value: ${GREEN}< 60 seconds${RESET}"
echo ""
echo -e "  Works with any Kafka broker. No Avro migration."
echo -e "  Schema lives in Git. PRs, diffs, code review — for data."
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
