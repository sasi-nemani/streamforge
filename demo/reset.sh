#!/usr/bin/env bash
# =============================================================================
# demo/reset.sh — Full reset and fresh start for StreamForge local + GCP demo
#
# What this script does:
#   1. Kill any existing ngrok, feed_all.py, and streamforge watch processes
#   2. Tear down Kafka containers + volumes (clean slate)
#   3. Start ngrok on port 9094 (the EXTERNAL Kafka listener)
#   4. Auto-detect the ngrok public address from the ngrok local API
#   5. Start Kafka with dual listeners:
#        LOCAL  (9092) → advertised as localhost:9092  (for local feed_all.py)
#        EXTERNAL (9094) → advertised as ngrok address  (for GCP VM)
#   6. Wait for Kafka to be healthy
#   7. Start feed_all.py in the background (uses LOCAL 9092 — no ngrok needed)
#   8. Print the KAFKA_BOOTSTRAP_SERVERS value to use for GCP deployment
#
# Usage:
#   bash demo/reset.sh                    # preseed 500 events then live mode
#   bash demo/reset.sh --no-feed          # just Kafka + ngrok, no producer
#   bash demo/reset.sh --preseed 1000     # custom preseed count
#
# After this script: in another terminal run:
#   KAFKA_BOOTSTRAP_SERVERS=<shown address> bash deploy/gcp.sh up
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Args ──────────────────────────────────────────────────────────────────────
START_FEED=true
PRESEED=500
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-feed)    START_FEED=false; shift ;;
        --preseed)    PRESEED="$2"; shift 2 ;;
        --preseed=*)  PRESEED="${1#--preseed=}"; shift ;;
        *) echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
done

# ── Colours ───────────────────────────────────────────────────────────────────
_G='\033[0;32m'; _Y='\033[1;33m'; _R='\033[0;31m'; _C='\033[0;36m'
_B='\033[1m'; _D='\033[2m'; _X='\033[0m'

info()    { echo -e "${_C}[reset]${_X} $*"; }
success() { echo -e "${_G}[reset]${_X} $*"; }
warn()    { echo -e "${_Y}[reset]${_X} $*"; }
error()   { echo -e "${_R}[reset] ERROR:${_X} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Prerequisites ─────────────────────────────────────────────────────────────
command -v docker   >/dev/null 2>&1 || die "docker not found."
command -v ngrok    >/dev/null 2>&1 || die "ngrok not found. Install: https://ngrok.com/download"
command -v python3  >/dev/null 2>&1 || die "python3 not found."
command -v curl     >/dev/null 2>&1 || die "curl not found."

# ── Load demo/.env if present (for API keys, custom rates) ───────────────────
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/.env"
    set +a
    info "Loaded demo/.env"
fi

echo ""
echo -e "${_B}${_C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_X}"
echo -e "${_B}${_C}  StreamForge — Reset & Fresh Start${_X}"
echo -e "${_B}${_C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_X}"
echo ""

# =============================================================================
# STEP 1 — Kill existing processes
# =============================================================================
info "Stopping any running StreamForge processes..."

# Stop feed_all.py
if pgrep -f "feed_all.py" >/dev/null 2>&1; then
    pkill -f "feed_all.py" 2>/dev/null || true
    info "  ✓ Stopped feed_all.py"
fi

# Stop streamforge watch
if pgrep -f "streamforge watch" >/dev/null 2>&1; then
    pkill -f "streamforge watch" 2>/dev/null || true
    info "  ✓ Stopped streamforge watch"
fi

# Stop existing ngrok (any instance)
if pgrep -x "ngrok" >/dev/null 2>&1; then
    pkill -x "ngrok" 2>/dev/null || true
    sleep 1  # give ngrok a moment to release the port
    info "  ✓ Stopped existing ngrok"
fi

# =============================================================================
# STEP 2 — Tear down Kafka (remove volumes for a clean slate)
# =============================================================================
info "Tearing down Kafka containers and volumes..."
cd "$SCRIPT_DIR"
docker compose down -v --remove-orphans 2>/dev/null || true
success "  ✓ Kafka containers and volumes removed"
cd "$REPO_ROOT"

# =============================================================================
# STEP 3 — Start ngrok on the EXTERNAL listener port (9094)
# =============================================================================
info "Starting ngrok tcp tunnel on port 9094..."

# Start ngrok in background, logging to a temp file so we can debug if needed
NGROK_LOG="$(mktemp /tmp/ngrok-streamforge-XXXXXX.log)"
ngrok tcp 9094 --log=stdout --log-format=json > "$NGROK_LOG" 2>&1 &
NGROK_PID=$!

# Poll the ngrok local API until the tunnel is up (up to 30s)
NGROK_ADDR=""
for i in $(seq 1 30); do
    sleep 1
    # ngrok exposes tunnel info at http://localhost:4040/api/tunnels
    _raw="$(curl -sf http://localhost:4040/api/tunnels 2>/dev/null || true)"
    if [[ -n "$_raw" ]]; then
        # Extract first tunnel's public_url, strip "tcp://"
        _url="$(echo "$_raw" | python3 -c "
import sys, json
tunnels = json.load(sys.stdin).get('tunnels', [])
# prefer the tcp tunnel on 9094
for t in tunnels:
    pu = t.get('public_url','')
    if pu.startswith('tcp://'):
        print(pu.replace('tcp://','').strip())
        break
" 2>/dev/null || true)"
        if [[ -n "$_url" ]]; then
            NGROK_ADDR="$_url"
            break
        fi
    fi
    [[ $((i % 5)) -eq 0 ]] && info "  waiting for ngrok tunnel... ($i s)"
done

if [[ -z "$NGROK_ADDR" ]]; then
    error "ngrok tunnel did not come up after 30 s."
    error "ngrok log: $NGROK_LOG"
    error "Check if you're logged in: ngrok config check"
    kill "$NGROK_PID" 2>/dev/null || true
    exit 1
fi

success "  ✓ ngrok tunnel: ${_B}tcp://$NGROK_ADDR${_X} → localhost:9094"

# =============================================================================
# STEP 4 — Start Kafka with dual listeners
#   LOCAL   (9092) → localhost:9092      (local feed_all.py uses this)
#   EXTERNAL (9094) → ngrok address      (GCP VM uses this)
# =============================================================================
info "Starting Kafka with dual listeners..."
cd "$SCRIPT_DIR"
KAFKA_NGROK_ADDR="$NGROK_ADDR" docker compose up -d
cd "$REPO_ROOT"

# Wait for Kafka health check to pass (up to 90s)
info "Waiting for Kafka to become healthy..."
_HEALTHY=false
for i in $(seq 1 18); do
    sleep 5
    _status="$(docker inspect --format='{{.State.Health.Status}}' kafka-streamforge-demo 2>/dev/null || echo "missing")"
    if [[ "$_status" == "healthy" ]]; then
        _HEALTHY=true
        break
    fi
    [[ $((i % 2)) -eq 0 ]] && info "  Kafka status: $_status (${i}×5 s)"
done

if [[ "$_HEALTHY" != "true" ]]; then
    error "Kafka did not become healthy after 90 s."
    docker logs kafka-streamforge-demo 2>&1 | tail -20
    exit 1
fi
success "  ✓ Kafka healthy"

# Verify both listeners are registered
_listeners="$(docker logs kafka-streamforge-demo 2>&1 | grep -i "Registered broker" | tail -1 || true)"
[[ -n "$_listeners" ]] && info "  $_listeners"

# =============================================================================
# STEP 5 — Start the event producer (uses LOCAL listener on localhost:9092)
# =============================================================================
if [[ "$START_FEED" == "true" ]]; then
    BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
    # Always use local address for feed — GCP uses ngrok
    FEED_BROKERS="localhost:9092"

    LOG_DIR="logs"
    mkdir -p "$LOG_DIR"

    info "Starting event producer (preseed=$PRESEED, then live)..."
    info "  Broker: $FEED_BROKERS (LOCAL listener — no ngrok needed)"

    # Kill any stale instance before starting
    pkill -f "feed_all.py" 2>/dev/null || true

    PAYMENT_RATE="${PAYMENT_RATE:-10}"
    BOOKING_RATE="${BOOKING_RATE:-5}"
    IOT_RATE="${IOT_RATE:-25}"
    WIKI_RATE="${WIKI_RATE:-3}"

    python3 "$SCRIPT_DIR/feed_all.py" \
        --brokers "$FEED_BROKERS" \
        --preseed "$PRESEED" \
        --payment-rate "$PAYMENT_RATE" \
        --booking-rate "$BOOKING_RATE" \
        --iot-rate    "$IOT_RATE" \
        --wiki-rate   "$WIKI_RATE" \
        >> "$LOG_DIR/producer.log" 2>&1 &
    FEED_PID=$!
    success "  ✓ Producer running (PID $FEED_PID) → $LOG_DIR/producer.log"
    info "  Rates: payment=${PAYMENT_RATE}/s  booking=${BOOKING_RATE}/s  iot=${IOT_RATE}/s  wiki=${WIKI_RATE}/s"
fi

# =============================================================================
# STEP 6 — Print summary and GCP instructions
# =============================================================================
echo ""
echo -e "${_B}${_G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_X}"
echo -e "${_B}${_G}  ✓ StreamForge local stack is running${_X}"
echo -e "${_B}${_G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${_X}"
echo ""
echo -e "  ${_B}Kafka listeners:${_X}"
echo -e "    LOCAL    → ${_B}localhost:9092${_X}   (feed_all.py, local tools)"
echo -e "    EXTERNAL → ${_B}$NGROK_ADDR${_X}  (GCP VM via ngrok)"
echo ""
echo -e "  ${_B}Kafka UI:${_X}   http://localhost:8080"
echo -e "  ${_B}ngrok UI:${_X}   http://localhost:4040"
if [[ "$START_FEED" == "true" ]]; then
echo -e "  ${_B}Feed log:${_X}   tail -f logs/producer.log"
fi
echo ""
echo -e "  ${_B}${_Y}To deploy on GCP — run in a separate terminal:${_X}"
echo ""
echo -e "    ${_B}KAFKA_BOOTSTRAP_SERVERS=${NGROK_ADDR} bash deploy/gcp.sh up${_X}"
echo ""
echo -e "  ${_D}(The GCP VM will connect to Kafka via the ngrok EXTERNAL listener)${_X}"
echo ""
echo -e "  ${_D}ngrok PID: $NGROK_PID  |  log: $NGROK_LOG${_X}"
echo ""

# Export for subshells / sourcing
export KAFKA_NGROK_ADDR="$NGROK_ADDR"
export KAFKA_BOOTSTRAP_SERVERS_GCP="$NGROK_ADDR"
