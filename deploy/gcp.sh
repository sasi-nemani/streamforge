#!/usr/bin/env bash
# =============================================================================
# deploy/gcp.sh — StreamForge GCP Compute Engine deployment
#
# USAGE:
#   bash deploy/gcp.sh [up|down|status|logs|ssh]
#
# REQUIRED (prompted interactively if not set):
#   KAFKA_BOOTSTRAP_SERVERS   ngrok address: X.tcp.ngrok.io:PORT
#                             Run `ngrok tcp 9094` locally to get this.
#                             (9094 is the EXTERNAL listener; 9092 stays local)
#
# OPTIONAL (all have sensible defaults):
#   KAFKA_TOPICS              comma-separated topic list  [events.all]
#   GROQ_API_KEY              LLM key — primary (free at console.groq.com)
#   OPENAI_API_KEY            LLM key — fallback (gpt-4o-mini)
#   OPENROUTER_API_KEY        LLM key — last fallback before statistical
#   GCP_PROJECT               default: loonstreamforge
#   GCP_ZONE                  default: us-central1-a  (free tier)
#   GCP_MACHINE_TYPE          default: e2-micro        (free tier)
#   GCP_INSTANCE_NAME         default: streamforge-watch
#   GCP_DISK_SIZE_GB          default: 30              (free tier max)
#   GCP_REPO_URL              default: git remote get-url origin
#   GCP_REPO_BRANCH           default: current branch
#   SF_SAMPLE_SIZE            default: 400
#   SF_MIN_CONFIDENCE         default: 0.70  (above stat-fallback 0.60)
#   SF_RETRY_INTERVAL         default: 30    (seconds between init retries)
#   SF_WATCH_INTERVAL         default: 30    (drift poll interval)
#   SF_WARMUP_CYCLES          default: 10 (LEARNING phase — no Tier-1/2 alerts)
#   SF_STABILITY_CYCLES       default: 3  (consecutive clean cycles to declare STABLE)
#   SF_CONSECUTIVE_DRIFT_THRESHOLD default: 2 (STABLE phase flap suppression)
#   SF_NEW_CLUSTER_THRESHOLD  default: 0.12
#   SF_MIN_EVENTS_BEFORE_INIT default: SF_SAMPLE_SIZE (400) — gate before init
#   SF_LOG_LEVEL              default: INFO
#
# COMMANDS:
#   up      Create VM, install StreamForge, launch per-topic init loops
#   down    Delete the VM (prompts for confirmation)
#   status  Show VM state, per-topic service status, recent log lines
#   logs    Tail watch log (or init log if still initialising)
#   ssh     Open an interactive SSH session
# =============================================================================
set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
_RED='\033[0;31m'; _GREEN='\033[0;32m'; _YELLOW='\033[1;33m'
_CYAN='\033[0;36m'; _DIM='\033[2m'; _RESET='\033[0m'
_BOLD='\033[1m'

info()    { echo -e "${_CYAN}[deploy]${_RESET} $*"; }
success() { echo -e "${_GREEN}[deploy]${_RESET} $*"; }
warn()    { echo -e "${_YELLOW}[deploy]${_RESET} $*"; }
error()   { echo -e "${_RED}[deploy] ERROR:${_RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Command ────────────────────────────────────────────────────────────────────
COMMAND="${1:-up}"
[[ "$COMMAND" =~ ^(up|down|status|logs|ssh)$ ]] || \
    die "Unknown command: $COMMAND. Use: up|down|status|logs|ssh"

# ── Prerequisites ──────────────────────────────────────────────────────────────
command -v gcloud >/dev/null 2>&1 || \
    die "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
command -v git >/dev/null 2>&1 || die "git not found."

# ── GCP parameters ─────────────────────────────────────────────────────────────
GCP_PROJECT="${GCP_PROJECT:-loonstreamforge}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-micro}"
GCP_INSTANCE_NAME="${GCP_INSTANCE_NAME:-streamforge-watch}"
GCP_DISK_SIZE_GB="${GCP_DISK_SIZE_GB:-30}"

# ── Repo ───────────────────────────────────────────────────────────────────────
GCP_REPO_URL="${GCP_REPO_URL:-$(git remote get-url origin 2>/dev/null || echo "")}"
[[ -n "$GCP_REPO_URL" ]] || \
    die "GCP_REPO_URL is not set and 'git remote get-url origin' failed.\nSet GCP_REPO_URL explicitly."
GCP_REPO_BRANCH="${GCP_REPO_BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"

# ── Topics ─────────────────────────────────────────────────────────────────────
KAFKA_TOPICS="${KAFKA_TOPICS:-events.payments,events.bookings,events.iot,events.wiki}"

# ── LLM keys ───────────────────────────────────────────────────────────────────
# Inference cascade: Groq → OpenAI → OpenRouter → statistical fallback
GROQ_API_KEY="${GROQ_API_KEY:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# ── VCS / GitHub integration ────────────────────────────────────────────────────
# Required for schema-as-code: StreamForge commits inferred schemas to git and
# opens PRs on drift acceptance. Set these to enable automatic schema commits
# from the GCP watch VM.
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_REPO="${GITHUB_REPO:-}"

# ── StreamForge tuning ─────────────────────────────────────────────────────────
# SF_MIN_EVENTS_BEFORE_INIT: don't attempt init until at least this many events
# have accumulated in the topic. Defaults to SF_SAMPLE_SIZE (no point inferring
# from fewer events than we'll sample).
SF_SAMPLE_SIZE="${SF_SAMPLE_SIZE:-400}"
SF_MIN_EVENTS_BEFORE_INIT="${SF_MIN_EVENTS_BEFORE_INIT:-$SF_SAMPLE_SIZE}"
SF_MIN_CONFIDENCE="${SF_MIN_CONFIDENCE:-0.70}"
SF_RETRY_INTERVAL="${SF_RETRY_INTERVAL:-30}"
SF_WATCH_INTERVAL="${SF_WATCH_INTERVAL:-30}"
# Stability state machine:
#   LEARNING (WARMUP_CYCLES): observe, log, no Tier-1/2 alerts — Tier-3 always fires
#   STABILIZING (STABILITY_CYCLES): require N consecutive clean cycles before going STABLE
#   STABLE: full alerting, but Tier-1/2 requires CONSECUTIVE_DRIFT_THRESHOLD cycles to alert
SF_WARMUP_CYCLES="${SF_WARMUP_CYCLES:-10}"
SF_STABILITY_CYCLES="${SF_STABILITY_CYCLES:-3}"
SF_CONSECUTIVE_DRIFT_THRESHOLD="${SF_CONSECUTIVE_DRIFT_THRESHOLD:-2}"
SF_NEW_CLUSTER_THRESHOLD="${SF_NEW_CLUSTER_THRESHOLD:-0.12}"
SF_LOG_LEVEL="${SF_LOG_LEVEL:-INFO}"

# ── ngrok / Kafka broker resolution ───────────────────────────────────────────
# Only needed for 'up' command
if [[ "$COMMAND" == "up" ]]; then
    if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
        echo ""
        echo -e "${_YELLOW}┌─────────────────────────────────────────────────────────┐${_RESET}"
        echo -e "${_YELLOW}│  KAFKA_BOOTSTRAP_SERVERS is not set.                    │${_RESET}"
        echo -e "${_YELLOW}│                                                         │${_RESET}"
        echo -e "${_YELLOW}│  To expose your local Kafka to GCP, open a NEW          │${_RESET}"
        echo -e "${_YELLOW}│  terminal and run:                                      │${_RESET}"
        echo -e "${_YELLOW}│                                                         │${_RESET}"
        echo -e "${_YELLOW}│    ${_BOLD}ngrok tcp 9094${_YELLOW}                                    │${_RESET}"
        echo -e "${_YELLOW}│                                                         │${_RESET}"
        echo -e "${_YELLOW}│  (9094 is the EXTERNAL listener — 9092 is local-only)   │${_RESET}"
        echo -e "${_YELLOW}│                                                         │${_RESET}"
        echo -e "${_YELLOW}│  Then copy the address shown:                           │${_RESET}"
        echo -e "${_YELLOW}│    Forwarding  tcp://X.tcp.ngrok.io:PORT -> ...         │${_RESET}"
        echo -e "${_YELLOW}│  and paste just the HOST:PORT part below.               │${_RESET}"
        echo -e "${_YELLOW}└─────────────────────────────────────────────────────────┘${_RESET}"
        echo ""
        read -rp "  ngrok address (e.g. 2.tcp.ngrok.io:12345): " KAFKA_BOOTSTRAP_SERVERS
        [[ -n "$KAFKA_BOOTSTRAP_SERVERS" ]] || die "KAFKA_BOOTSTRAP_SERVERS is required."
    fi

    # Validate the address is reachable
    _NGROK_HOST="${KAFKA_BOOTSTRAP_SERVERS%%:*}"
    _NGROK_PORT="${KAFKA_BOOTSTRAP_SERVERS##*:}"
    info "Testing connectivity to ${KAFKA_BOOTSTRAP_SERVERS}..."
    if command -v nc >/dev/null 2>&1; then
        nc -zw5 "$_NGROK_HOST" "$_NGROK_PORT" 2>/dev/null && \
            success "Connection OK — ngrok tunnel is live." || \
            warn "Could not reach ${KAFKA_BOOTSTRAP_SERVERS}. Is ngrok running? Continuing anyway..."
    else
        warn "nc not available — skipping connectivity check."
    fi

    if [[ -z "$GROQ_API_KEY" && -z "$OPENAI_API_KEY" && -z "$OPENROUTER_API_KEY" ]]; then
        warn "No LLM API key set. Schema inference will use statistical fallback (confidence capped at 0.60)."
        warn "Set GROQ_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY for LLM-quality inference."
        warn "  Free Groq key: https://console.groq.com"
    fi
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
# Convert topic name to a safe slug for systemd service names and log files
# e.g.  events.all  →  events-all
_slug() { echo "$1" | tr './' '-' | tr -cd 'a-zA-Z0-9-'; }

# SSH / SCP wrappers
_ssh() {
    gcloud compute ssh "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet -- "$@"
}

_scp_to() {
    gcloud compute scp \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet \
        "$1" "${GCP_INSTANCE_NAME}:$2"
}

# =============================================================================
# ── PROVIDER: GCP ─────────────────────────────────────────────────────────────
# =============================================================================

_gcp_vm_exists() {
    gcloud compute instances describe "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --format="value(status)" 2>/dev/null | grep -q "RUNNING"
}

_gcp_create_vm() {
    info "Creating VM: ${GCP_INSTANCE_NAME} (${GCP_MACHINE_TYPE}, ${GCP_ZONE}) — free tier"
    gcloud compute instances create "$GCP_INSTANCE_NAME" \
        --project="$GCP_PROJECT" \
        --zone="$GCP_ZONE" \
        --machine-type="$GCP_MACHINE_TYPE" \
        --image-family=debian-12 \
        --image-project=debian-cloud \
        --boot-disk-size="${GCP_DISK_SIZE_GB}GB" \
        --boot-disk-type=pd-standard \
        --metadata=enable-oslogin=true \
        --quiet
    success "VM created."

    info "Waiting for SSH to become available..."
    local max=24 i=0
    until gcloud compute ssh "$GCP_INSTANCE_NAME" \
            --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
            --quiet --command="echo ok" 2>/dev/null; do
        i=$(( i + 1 ))
        [[ $i -lt $max ]] || die "VM never became SSH-ready after $(( max * 5 ))s."
        echo -n "."
        sleep 5
    done
    echo ""
    success "SSH ready."
}

_gcp_delete_vm() {
    warn "This will PERMANENTLY DELETE instance: ${GCP_INSTANCE_NAME} (${GCP_ZONE})"
    read -rp "  Type the instance name to confirm: " confirm
    [[ "$confirm" == "$GCP_INSTANCE_NAME" ]] || die "Confirmation did not match. Aborting."
    gcloud compute instances delete "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet
    success "Instance deleted."
}

# =============================================================================
# ── CODE UPLOAD ── (local tarball → gcloud scp — no git auth needed)
# =============================================================================

_upload_code() {
    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # streamforge-mvp/
    local tarball="/tmp/streamforge-deploy-$(date +%s).tar.gz"

    info "Packaging code from: ${src_dir}"
    tar -czf "$tarball" \
        --exclude='*.pyc' \
        --exclude='*/__pycache__' \
        --exclude='*/.venv' \
        --exclude='*/events' \
        --exclude='*/drift_reports' \
        --exclude='*/schemas' \
        --exclude='*/logs' \
        --exclude='*/.git' \
        -C "$(dirname "$src_dir")" \
        "$(basename "$src_dir")"
    local size
    size=$(du -sh "$tarball" | cut -f1)
    info "Uploading code tarball (${size}) to VM..."

    gcloud compute scp "$tarball" "${GCP_INSTANCE_NAME}:/tmp/streamforge-mvp.tar.gz" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet
    rm -f "$tarball"

    # Write .env.deploy locally and SCP it — avoids nested-heredoc variable
    # substitution bugs where keys silently become empty strings.
    local env_file="/tmp/streamforge-env-$(date +%s).deploy"
    printf 'KAFKA_BOOTSTRAP_SERVERS=%s\n' "$KAFKA_BOOTSTRAP_SERVERS" >  "$env_file"
    printf 'GROQ_API_KEY=%s\n'            "$GROQ_API_KEY"            >> "$env_file"
    printf 'OPENAI_API_KEY=%s\n'          "$OPENAI_API_KEY"          >> "$env_file"
    printf 'OPENROUTER_API_KEY=%s\n'      "$OPENROUTER_API_KEY"      >> "$env_file"
    printf 'STREAMFORGE_LOG_LEVEL=%s\n'   "$SF_LOG_LEVEL"            >> "$env_file"
    printf 'STREAMFORGE_LOG_DIR=%s\n'     "logs"                     >> "$env_file"
    printf 'STREAMFORGE_NEW_CLUSTER_THRESHOLD=%s\n'        "$SF_NEW_CLUSTER_THRESHOLD"        >> "$env_file"
    printf 'STREAMFORGE_WARMUP_CYCLES=%s\n'                "$SF_WARMUP_CYCLES"                >> "$env_file"
    printf 'STREAMFORGE_STABILITY_CYCLES=%s\n'             "$SF_STABILITY_CYCLES"             >> "$env_file"
    printf 'STREAMFORGE_CONSECUTIVE_DRIFT_THRESHOLD=%s\n'  "$SF_CONSECUTIVE_DRIFT_THRESHOLD"  >> "$env_file"
    printf 'GITHUB_TOKEN=%s\n'   "$GITHUB_TOKEN"   >> "$env_file"
    printf 'GITHUB_REPO=%s\n'    "$GITHUB_REPO"    >> "$env_file"

    # Validate keys before uploading
    local has_key=false
    [[ -n "$GROQ_API_KEY" || -n "$OPENAI_API_KEY" || -n "$OPENROUTER_API_KEY" ]] && has_key=true
    if [[ "$has_key" == false ]]; then
        warn "WARNING: all LLM API keys are empty — inference will use statistical fallback only."
    else
        info "LLM key(s) present — writing to .env.deploy"
    fi

    # Validate GitHub token for schema-as-code integration
    if [[ -z "$GITHUB_TOKEN" ]]; then
        warn "WARNING: GITHUB_TOKEN is not set — schema commits and PRs will be disabled on the VM."
        warn "  Set GITHUB_TOKEN to enable automatic schema-as-code commits from GCP."
    else
        info "GITHUB_TOKEN present — schema-as-code VCS integration enabled."
    fi

    gcloud compute scp "$env_file" "${GCP_INSTANCE_NAME}:/tmp/streamforge.env.deploy" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet
    _ssh "mkdir -p \$HOME/streamforge/streamforge-mvp && mv /tmp/streamforge.env.deploy \$HOME/streamforge/streamforge-mvp/.env.deploy && chmod 600 \$HOME/streamforge/streamforge-mvp/.env.deploy"
    rm -f "$env_file"
    success "Code and .env.deploy uploaded."
}

# =============================================================================
# ── REMOTE SETUP ── (provider-agnostic, runs via SSH)
# =============================================================================

_remote_setup() {
    # Upload code first (no git auth required)
    _upload_code

    info "Installing system packages and StreamForge on the VM..."
    _ssh "bash -s" <<REMOTE_SETUP
set -euo pipefail

# ── System packages ──────────────────────────────────────────────────────────
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv tmux logrotate netcat-openbsd 2>/dev/null

# ── 2 GB swap (critical on e2-micro / 1 GB RAM) ──────────────────────────────
if ! grep -q /swapfile /proc/swaps 2>/dev/null; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap -q /swapfile
    sudo /sbin/swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    echo "Swap: created 2 GB"
else
    echo "Swap: already configured"
fi

# ── Extract uploaded code ─────────────────────────────────────────────────────
REPO_DIR="\$HOME/streamforge/streamforge-mvp"
mkdir -p "\$HOME/streamforge"
tar -xzf /tmp/streamforge-mvp.tar.gz -C "\$HOME/streamforge/"
rm -f /tmp/streamforge-mvp.tar.gz
echo "Code extracted to \$REPO_DIR"

# ── Python venv + install ─────────────────────────────────────────────────────
cd "\$REPO_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[kafka]"
.venv/bin/pip install --quiet kafka-python  # explicit install — extras may be skipped on re-deploy
echo "StreamForge installed OK"

mkdir -p logs schemas drift_reports
echo ".env.deploy will be uploaded separately."

# ── logrotate ─────────────────────────────────────────────────────────────────
sudo tee /etc/logrotate.d/streamforge >/dev/null <<LOGROTATE
\$HOME/streamforge/streamforge-mvp/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
LOGROTATE
echo "logrotate configured."
REMOTE_SETUP
    success "Remote setup complete."
}

# =============================================================================
# ── PER-TOPIC INIT LOOP ── (runs in a tmux window on the VM)
# =============================================================================
# Writes the init loop script locally, SCPs it, then launches it in tmux.
# Avoids nested heredoc variable-expansion issues entirely.

_remote_launch_topic() {
    local topic="$1"
    local slug
    slug="$(_slug "$topic")"

    info "Launching init loop for topic: ${topic} (slug: ${slug})"

    # ── Write init loop script locally, then SCP it ───────────────────────────
    local tmp_script="/tmp/sf_init_loop_${slug}.sh"

    cat > "$tmp_script" <<LOOP_EOF
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="\$HOME/streamforge/streamforge-mvp"
VENV="\$REPO_DIR/.venv/bin/python"
LOG_DIR="\$REPO_DIR/logs"
SCHEMA_DIR="\$REPO_DIR/schemas"

TOPIC="${topic}"
SLUG="${slug}"
SF_SAMPLE_SIZE="${SF_SAMPLE_SIZE}"
SF_MIN_EVENTS_BEFORE_INIT="${SF_MIN_EVENTS_BEFORE_INIT}"
SF_MIN_CONFIDENCE="${SF_MIN_CONFIDENCE}"
SF_RETRY_INTERVAL="${SF_RETRY_INTERVAL}"
SF_WATCH_INTERVAL="${SF_WATCH_INTERVAL}"

cd "\$REPO_DIR"
mkdir -p "\$LOG_DIR"

ts()      { date '+%H:%M:%S'; }
log()     { echo "[\$(ts)] \$*" | tee -a "\$LOG_DIR/init_\${SLUG}.log"; }
divider() { echo "────────────────────────────────────────────────────────"; }

divider
log "TOPIC       : \$TOPIC"
log "SAMPLE SIZE : \$SF_SAMPLE_SIZE   MIN CONFIDENCE: \$SF_MIN_CONFIDENCE"
log "RETRY EVERY : \${SF_RETRY_INTERVAL}s"
divider

_check_confidence() {
    "\$VENV" - "\$SCHEMA_DIR" "\$SF_MIN_CONFIDENCE" <<'PYEOF'
import yaml, pathlib, sys

schemas = pathlib.Path(sys.argv[1])
threshold = float(sys.argv[2])
confidences = []

for pf in schemas.glob("*/profile.yaml"):
    d = yaml.safe_load(open(pf))
    subs = d.get("sub_schemas", [])
    if subs:
        avg = sum(s.get("inference_confidence", 0) for s in subs) / len(subs)
        print(f"  profile: {len(subs)} clusters, avg confidence = {avg:.3f}")
        confidences.append(avg)

for sf in schemas.glob("*/schema.yaml"):
    if (sf.parent / "profile.yaml").exists():
        continue
    d = yaml.safe_load(open(sf))
    c = d.get("inference_confidence", 0)
    print(f"  schema: confidence = {c:.3f}")
    confidences.append(c)

if not confidences:
    print("  No schema output found yet.")
    sys.exit(1)

overall = sum(confidences) / len(confidences)
verdict = "PASS" if overall >= threshold else "FAIL"
print(f"  Overall: {overall:.3f}  threshold: {threshold:.3f}  -> {verdict}")
sys.exit(0 if overall >= threshold else 1)
PYEOF
}

_install_watch_service() {
    log "Installing systemd watch service: streamforge-watch-\${SLUG}"
    sudo tee "/etc/systemd/system/streamforge-watch-\${SLUG}.service" > /dev/null <<UNIT
[Unit]
Description=StreamForge drift watch -- \${TOPIC}
After=network.target

[Service]
Type=simple
User=\${USER}
WorkingDirectory=\${REPO_DIR}
EnvironmentFile=\${REPO_DIR}/.env.deploy
ExecStart=\${VENV} -m streamforge watch kafka://\${TOPIC} --interval \${SF_WATCH_INTERVAL} --sample-size 200
StandardOutput=append:\${LOG_DIR}/watch_\${SLUG}.log
StandardError=append:\${LOG_DIR}/watch_\${SLUG}.log
Restart=on-failure
RestartSec=15s
StartLimitBurst=5
StartLimitIntervalSec=120

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable "streamforge-watch-\${SLUG}" --quiet
    sudo systemctl restart "streamforge-watch-\${SLUG}"
    sleep 2
    if sudo systemctl is-active "streamforge-watch-\${SLUG}" --quiet; then
        log "Watch service ACTIVE -- drifts logged to \$LOG_DIR/watch_\${SLUG}.log"
    else
        log "Watch service failed to start -- check: journalctl -u streamforge-watch-\${SLUG}"
    fi
}

# Count total messages in a Kafka topic (end_offset - begin_offset, all partitions).
# Prints the count and exits 0 on success.
# Exits 2 on library/connection error (caller should skip the gate, not block).
_count_kafka_events() {
    "\$VENV" - "\$KAFKA_BOOTSTRAP_SERVERS" "\$TOPIC" <<'PYEOF'
import sys
brokers, topic = sys.argv[1], sys.argv[2]
try:
    try:
        from confluent_kafka import Consumer, TopicPartition
        c = Consumer({"bootstrap.servers": brokers, "group.id": "_sf_count_probe",
                      "socket.timeout.ms": 10000})
        meta = c.list_topics(topic, timeout=10)
        if topic not in meta.topics or meta.topics[topic].error:
            c.close(); print(0); sys.exit(0)
        parts = [TopicPartition(topic, p) for p in meta.topics[topic].partitions]
        total = sum(c.get_watermark_offsets(tp, timeout=8)[1] -
                    c.get_watermark_offsets(tp, timeout=8)[0] for tp in parts)
        c.close(); print(total); sys.exit(0)
    except ImportError:
        pass
    # kafka-python: c.topics() forces a full metadata refresh (unlike poll())
    from kafka import KafkaConsumer, TopicPartition as TP
    c = KafkaConsumer(bootstrap_servers=brokers, request_timeout_ms=15000,
                      connections_max_idle_ms=20000)
    all_topics = c.topics()   # blocks until metadata is fully loaded
    partitions = c.partitions_for_topic(topic) or set()
    if not partitions:
        c.close(); print(0); sys.exit(0)
    tps = [TP(topic, p) for p in partitions]
    c.assign(tps)
    ends   = c.end_offsets(tps)
    begins = c.beginning_offsets(tps)
    total  = sum(ends[tp] - begins[tp] for tp in tps)
    c.close(); print(total); sys.exit(0)
except Exception as e:
    print(f"count_error: {e}", file=sys.stderr)
    sys.exit(2)
PYEOF
}

attempt=1
EVENT_COUNT="unknown"
while true; do
    # Re-source .env.deploy each iteration so live key updates take effect
    set -a; source "\$REPO_DIR/.env.deploy"; set +a

    # ── Pre-check: wait until enough events have accumulated ──────────────────
    set +e
    _RAW_COUNT=\$(_count_kafka_events 2>/tmp/sf_count_err_\${SLUG}.log)
    COUNT_EXIT=\$?
    set -e

    if [ "\$COUNT_EXIT" -eq 2 ]; then
        _ERR=\$(cat /tmp/sf_count_err_\${SLUG}.log 2>/dev/null | head -1 || echo 'kafka lib unavailable')
        log "[attempt \${attempt}] event-count unavailable (\${_ERR}) — proceeding to init"
    else
        EVENT_COUNT="\$_RAW_COUNT"
        if [ "\$EVENT_COUNT" -lt "\$SF_MIN_EVENTS_BEFORE_INIT" ]; then
            log "[attempt \${attempt}] ACCUMULATING — \${EVENT_COUNT} events in '\${TOPIC}' (need \${SF_MIN_EVENTS_BEFORE_INIT}). Waiting \${SF_RETRY_INTERVAL}s..."
            (( attempt++ ))
            sleep "\$SF_RETRY_INTERVAL"
            divider
            continue
        fi
        log "[attempt \${attempt}] EVENTS OK — \${EVENT_COUNT} events in '\${TOPIC}' (>= \${SF_MIN_EVENTS_BEFORE_INIT})"
    fi

    log "[attempt \${attempt}] running streamforge init  [topic=\${TOPIC}  sample=\${SF_SAMPLE_SIZE}  events=\${EVENT_COUNT}]"
    set +e
    "\$VENV" -m streamforge init "kafka://\${TOPIC}" \
        --sample-size "\$SF_SAMPLE_SIZE" \
        --output schemas \
        2>&1 | tee -a "\$LOG_DIR/init_\${SLUG}.log"
    INIT_EXIT=\${PIPESTATUS[0]}
    set -e

    if [ "\$INIT_EXIT" -eq 0 ]; then
        log "[attempt \${attempt}] init exited OK — checking confidence  [events=\${EVENT_COUNT}]"
        if _check_confidence; then
            divider
            log "[attempt \${attempt}] INIT DONE — confidence >= \${SF_MIN_CONFIDENCE}  [events=\${EVENT_COUNT}]"
            log "Starting watch service..."
            _install_watch_service
            divider
            log "=== Topic \${TOPIC} is now WATCHING for drift  [seeded with \${EVENT_COUNT} events] ==="
            exit 0
        else
            log "[attempt \${attempt}] confidence below \${SF_MIN_CONFIDENCE} (need more events)  [events=\${EVENT_COUNT}]"
        fi
    else
        log "[attempt \${attempt}] init failed (exit \${INIT_EXIT})  [events=\${EVENT_COUNT}] — waiting \${SF_RETRY_INTERVAL}s"
    fi

    (( attempt++ ))
    sleep "\$SF_RETRY_INTERVAL"
    divider
done
LOOP_EOF

    # SCP to /tmp (no path expansion issues), then SSH to move into place
    gcloud compute scp "$tmp_script" \
        "${GCP_INSTANCE_NAME}:/tmp/sf_init_loop_${slug}.sh" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet
    rm -f "$tmp_script"
    _ssh "mv /tmp/sf_init_loop_${slug}.sh \$HOME/streamforge/streamforge-mvp/deploy/init_loop_${slug}.sh"

    # Make executable
    _ssh "chmod +x \$HOME/streamforge/streamforge-mvp/deploy/init_loop_${slug}.sh"

    # Create tmux session (overview window) if it doesn't already exist
    _ssh "tmux has-session -t streamforge 2>/dev/null || tmux new-session -d -s streamforge -n overview"

    # Kill any stale window for this slug (safe for re-deploy)
    _ssh "tmux kill-window -t 'streamforge:${slug}' 2>/dev/null || true"

    # Launch init loop in its own tmux window
    _ssh "tmux new-window -t streamforge -n '${slug}' \
        'bash \$HOME/streamforge/streamforge-mvp/deploy/init_loop_${slug}.sh; echo; echo done; read -r'"

    info "Init loop running in tmux window: ${slug}"
    info "Attach on VM: tmux attach -t streamforge"

    success "Init loop launched for: ${topic}"
}

# =============================================================================
# ── COMMANDS ──────────────────────────────────────────────────────────────────
# =============================================================================

cmd_up() {
    echo ""
    echo -e "${_CYAN}══════════════════════════════════════════════════════════${_RESET}"
    echo -e "${_CYAN}  StreamForge → GCP Compute Engine (free tier)${_RESET}"
    echo -e "${_CYAN}══════════════════════════════════════════════════════════${_RESET}"
    echo -e "  Instance     : ${GCP_INSTANCE_NAME}"
    echo -e "  Machine      : ${GCP_MACHINE_TYPE}  (${GCP_ZONE})"
    echo -e "  Project      : ${GCP_PROJECT}"
    echo -e "  Kafka broker : ${KAFKA_BOOTSTRAP_SERVERS}"
    echo -e "  Topics       : ${KAFKA_TOPICS}"
    echo -e "  Sample size  : ${SF_SAMPLE_SIZE}"
    echo -e "  Min confidence: ${SF_MIN_CONFIDENCE}  (retry every ${SF_RETRY_INTERVAL}s)"
    echo -e "  Watch interval: ${SF_WATCH_INTERVAL}s  |  Warmup: ${SF_WARMUP_CYCLES} cycles"
    echo -e "  Repo         : ${GCP_REPO_URL}  (${GCP_REPO_BRANCH})"
    echo ""

    if _gcp_vm_exists; then
        warn "Instance '${GCP_INSTANCE_NAME}' is already RUNNING."
        read -rp "  Re-deploy to existing instance? [y/N] " yn
        [[ "$yn" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
    else
        _gcp_create_vm
    fi

    _remote_setup

    # Launch one init loop per topic
    IFS=',' read -ra TOPIC_LIST <<< "$KAFKA_TOPICS"
    for topic in "${TOPIC_LIST[@]}"; do
        topic="${topic// /}"  # trim spaces
        _remote_launch_topic "$topic"
    done

    echo ""
    echo -e "${_GREEN}══════════════════════════════════════════════════════════${_RESET}"
    echo -e "${_GREEN}  Deployment complete — init loops running on VM${_RESET}"
    echo -e "${_GREEN}══════════════════════════════════════════════════════════${_RESET}"
    echo ""
    echo "  Each topic starts in ACCUMULATING state, transitions to WATCHING"
    echo "  automatically once inference confidence ≥ ${SF_MIN_CONFIDENCE}."
    echo ""
    echo "  Monitor all topics (live):"
    echo "    bash deploy/gcp.sh logs"
    echo ""
    echo "  Check per-topic status:"
    echo "    bash deploy/gcp.sh status"
    echo ""
    echo "  Attach to tmux session on VM:"
    echo "    bash deploy/gcp.sh ssh"
    echo "    tmux attach -t streamforge"
    echo ""
    echo "  Tear down:"
    echo "    bash deploy/gcp.sh down"
    echo ""
}

cmd_down() {
    _gcp_vm_exists || die "Instance '${GCP_INSTANCE_NAME}' not found in ${GCP_ZONE}."
    _gcp_delete_vm
}

cmd_status() {
    _gcp_vm_exists || die "Instance '${GCP_INSTANCE_NAME}' is not running."

    info "VM:"
    gcloud compute instances describe "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --format="table(name, status, machineType.basename(), zone.basename(), networkInterfaces[0].accessConfigs[0].natIP)"
    echo ""

    info "Per-topic status:"
    IFS=',' read -ra TOPIC_LIST <<< "$KAFKA_TOPICS"
    for topic in "${TOPIC_LIST[@]}"; do
        topic="${topic// /}"
        slug="$(_slug "$topic")"
        echo -e "  ${_BOLD}${topic}${_RESET}  (slug: ${slug})"
        _ssh "bash -s" <<STATUS_CHECK
set -euo pipefail
SLUG="${slug}"
REPO="\$HOME/streamforge/streamforge-mvp"

# systemd watch service state
SVC="streamforge-watch-\${SLUG}"
if systemctl is-active "\$SVC" --quiet 2>/dev/null; then
    echo "    ✓ Watch service: ACTIVE (WATCHING)"
elif systemctl is-failed "\$SVC" --quiet 2>/dev/null; then
    echo "    ✗ Watch service: FAILED"
else
    echo "    ⏳ Watch service: not started yet (still initialising)"
fi

# tmux window state
if tmux list-windows -t streamforge 2>/dev/null | grep -q "\${SLUG}"; then
    echo "    tmux window '${slug}': running"
fi

# Last 5 lines of most relevant log
WLOG="\$REPO/logs/watch_\${SLUG}.log"
ILOG="\$REPO/logs/init_\${SLUG}.log"
if [ -f "\$WLOG" ] && [ -s "\$WLOG" ]; then
    echo "    ── watch log (last 5) ──────────────────────────────"
    tail -5 "\$WLOG" | sed 's/^/    /'
elif [ -f "\$ILOG" ]; then
    echo "    ── init log (last 5) ───────────────────────────────"
    tail -5 "\$ILOG" | sed 's/^/    /'
else
    echo "    (no logs yet)"
fi
echo ""
STATUS_CHECK
    done

    info "Drift reports:"
    _ssh "ls -lht \$HOME/streamforge/streamforge-mvp/drift_reports/ 2>/dev/null | head -10 || echo '  (none yet)'"
}

cmd_logs() {
    _gcp_vm_exists || die "Instance '${GCP_INSTANCE_NAME}' is not running."

    IFS=',' read -ra TOPIC_LIST <<< "$KAFKA_TOPICS"
    if [[ ${#TOPIC_LIST[@]} -eq 1 ]]; then
        slug="$(_slug "${TOPIC_LIST[0]// /}")"
        info "Tailing logs for: ${TOPIC_LIST[0]} (Ctrl+C to stop)"
        # Prefer watch log; fall back to init log
        _ssh "bash -s" <<TAIL_LOG
REPO="\$HOME/streamforge/streamforge-mvp"
WLOG="\$REPO/logs/watch_${slug}.log"
ILOG="\$REPO/logs/init_${slug}.log"
if [ -f "\$WLOG" ] && [ -s "\$WLOG" ]; then
    tail -f "\$WLOG"
elif [ -f "\$ILOG" ]; then
    echo "--- Watch not started yet — showing init log ---"
    tail -f "\$ILOG"
else
    echo "No logs yet. Is the init loop running?"
fi
TAIL_LOG
    else
        # Multi-topic: tail all logs interleaved
        info "Streaming all topic logs (Ctrl+C to stop)..."
        TAIL_ARGS=""
        for topic in "${TOPIC_LIST[@]}"; do
            topic="${topic// /}"
            slug="$(_slug "$topic")"
            TAIL_ARGS+=" \$HOME/streamforge/streamforge-mvp/logs/watch_${slug}.log"
            TAIL_ARGS+=" \$HOME/streamforge/streamforge-mvp/logs/init_${slug}.log"
        done
        _ssh "tail -f $TAIL_ARGS 2>/dev/null || echo 'No logs yet.'"
    fi
}

cmd_ssh() {
    _gcp_vm_exists || die "Instance '${GCP_INSTANCE_NAME}' is not running."
    info "Opening SSH session (tip: run 'tmux attach -t streamforge' to see topic windows)"
    gcloud compute ssh "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT"
}

# ── Dispatch ───────────────────────────────────────────────────────────────────
case "$COMMAND" in
    up)     cmd_up ;;
    down)   cmd_down ;;
    status) cmd_status ;;
    logs)   cmd_logs ;;
    ssh)    cmd_ssh ;;
esac
