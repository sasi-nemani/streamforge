#!/usr/bin/env bash
# ============================================================================
# StreamForge Demo — One-time setup script
# ============================================================================
# Run this ONCE before the demo. Safe to re-run.
# Takes ~2-3 minutes on first run (Docker pull + seed).
#
# What it does:
#   1. Checks prerequisites (Docker, Python 3.11+)
#   2. Creates .env from template if not present
#   3. Starts Kafka + Kafka UI via Docker Compose
#   4. Waits for Kafka to be healthy
#   5. Creates the events.all topic (4 partitions)
#   6. Installs StreamForge with Kafka support
#   7. Pre-seeds 500 events so demo inference is instant
#   8. Verifies everything with kafka-ping
# ============================================================================

set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
DIM="\033[2m"
RESET="\033[0m"

info()    { echo -e "${BOLD}→${RESET} $*"; }
success() { echo -e "${GREEN}✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET} $*"; }
die()     { echo -e "${RED}✗ ERROR:${RESET} $*" >&2; exit 1; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   StreamForge Demo — Setup               ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── Step 1: Check prerequisites ────────────────────────────────────────────────
info "Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    die "Docker is not installed. Install from https://docs.docker.com/get-docker/"
fi

if ! docker info &>/dev/null; then
    die "Docker is not running. Start Docker Desktop and try again."
fi

if ! command -v python3 &>/dev/null; then
    die "python3 not found. Install Python 3.11+."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    die "Python 3.11+ required (found $PY_VERSION)."
fi

success "Prerequisites OK (Docker, Python $PY_VERSION)"

# ── Step 2: Environment file ───────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
TEMPLATE="$SCRIPT_DIR/.env.template"

if [ ! -f "$ENV_FILE" ]; then
    info "Creating .env from template..."
    cp "$TEMPLATE" "$ENV_FILE"
    warn "Created demo/.env — edit it to add your GROQ_API_KEY before running demo.sh"
    warn "Get a free key at: https://console.groq.com (30 seconds to sign up)"
    echo ""
fi

# Source the env file
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Validate API key is set and non-placeholder
API_KEY_VALUE="${GROQ_API_KEY:-${LLM_API_KEY:-${OPENAI_API_KEY:-}}}"
if [ -z "$API_KEY_VALUE" ] || [[ "$API_KEY_VALUE" == *"your_key_here"* ]]; then
    echo ""
    echo -e "${YELLOW}┌──────────────────────────────────────────────────────┐${RESET}"
    echo -e "${YELLOW}│  ACTION REQUIRED: Set your LLM API key               │${RESET}"
    echo -e "${YELLOW}│                                                      │${RESET}"
    echo -e "${YELLOW}│  Edit demo/.env and set GROQ_API_KEY    │${RESET}"
    echo -e "${YELLOW}│  Get a free key: https://console.groq.com            │${RESET}"
    echo -e "${YELLOW}│                                                      │${RESET}"
    echo -e "${YELLOW}│  You can complete setup now and add the key later.   │${RESET}"
    echo -e "${YELLOW}└──────────────────────────────────────────────────────┘${RESET}"
    echo ""
    warn "Continuing setup without API key (add it before running demo.sh)"
fi

# ── Step 3: Start Docker Compose ───────────────────────────────────────────────
info "Starting Kafka + Kafka UI via Docker Compose..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d

# ── Step 4: Wait for Kafka to be healthy ───────────────────────────────────────
info "Waiting for Kafka to be healthy (up to 90s)..."
KAFKA_CONTAINER="kafka-streamforge-demo"
ELAPSED=0
while true; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$KAFKA_CONTAINER" 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        success "Kafka is healthy"
        break
    fi
    if [ "$ELAPSED" -ge 90 ]; then
        die "Kafka did not become healthy within 90s. Check: docker logs $KAFKA_CONTAINER"
    fi
    echo -e "  ${DIM}[${ELAPSED}s] Kafka status: $STATUS — waiting...${RESET}"
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

# ── Step 5: Create events.all topic ───────────────────────────────────────────
info "Creating Kafka topic: events.all (4 partitions)..."
docker exec "$KAFKA_CONTAINER" \
    kafka-topics \
    --bootstrap-server localhost:9092 \
    --create \
    --topic events.all \
    --partitions 4 \
    --replication-factor 1 \
    --if-not-exists \
    2>&1 | grep -v "^$" || true
success "Topic events.all ready"

# ── Step 6: Install StreamForge with Kafka support ────────────────────────────
info "Installing StreamForge with Kafka support..."
pip install -e ".[kafka]" --quiet
success "StreamForge installed"

# ── Step 7: Pre-seed 500 events ───────────────────────────────────────────────
info "Pre-seeding 500 events into events.all (burst mode)..."
python3 "$SCRIPT_DIR/feed_all.py" \
    --brokers "${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}" \
    --preseed 500 \
    --no-live
success "Pre-seeded 500 events (125 per event type)"

# ── Step 8: Verify event count via broker offsets ─────────────────────────────
# Fix: kafka-ping uses auto_offset_reset=latest and returns "OK" even when
# 0 messages are received (producer already exited). Verify the actual offset
# count from the broker instead — this is unambiguous.
info "Verifying event count in topic..."
TOTAL_EVENTS=$(docker exec "$KAFKA_CONTAINER" \
    kafka-run-class kafka.tools.GetOffsetShell \
    --broker-list localhost:9092 \
    --topic events.all \
    --time -1 2>/dev/null \
    | awk -F: '{sum += $3} END {print sum}')
if [ "${TOTAL_EVENTS:-0}" -ge 500 ]; then
    success "Verified: ${TOTAL_EVENTS} events confirmed in events.all (expected 500+)"
else
    warn "Expected 500+ events, found ${TOTAL_EVENTS:-0} — seeding may have failed"
fi

# ── Clean demo output dirs ─────────────────────────────────────────────────────
info "Cleaning demo output directories..."
rm -rf "$REPO_ROOT/schemas/events.all" "$REPO_ROOT/drift_reports/events.all"
# Also remove stale watch checkpoint — a checkpoint from a previous session
# contains events inferred against a different schema and will cause false-positive
# drift on the very first watch poll.
rm -rf "$REPO_ROOT/schemas/events.all/.watch_state"
success "Output dirs clean (schemas/events.all, drift_reports/events.all, .watch_state)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║   Setup complete — ready to demo!                    ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Kafka UI:     ${BOLD}http://localhost:8080${RESET}  (browse topics + messages)"
echo -e "  Kafka broker: ${BOLD}localhost:9092${RESET}"
echo -e "  Topic:        ${BOLD}events.all${RESET}  (500 events seeded, 4 partitions)"
echo ""
if [ -z "$API_KEY_VALUE" ] || [[ "$API_KEY_VALUE" == *"your_key_here"* ]]; then
    echo -e "  ${YELLOW}⚠ REMINDER: Add GROQ_API_KEY to demo/.env before running demo.sh${RESET}"
    echo ""
fi
echo -e "  Run the demo:"
echo -e "    ${BOLD}source demo/.env && bash demo/demo.sh${RESET}"
echo ""
