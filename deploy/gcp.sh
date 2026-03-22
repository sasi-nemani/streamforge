#!/usr/bin/env bash
# =============================================================================
# deploy/gcp.sh — StreamForge single-node deployment on GCP Compute Engine
#
# USAGE:
#   bash deploy/gcp.sh [up|down|status|logs|ssh]
#
# REQUIRED INPUTS (env vars or interactive prompts):
#   KAFKA_BOOTSTRAP_SERVERS   e.g. 10.0.0.5:9092 or broker.example.com:9092
#   KAFKA_TOPIC               default: events.all
#
# OPTIONAL INPUTS (all have sensible defaults):
#   GROQ_API_KEY              LLM key for streamforge init
#   OPENROUTER_API_KEY        fallback LLM key
#   GCP_PROJECT               gcloud config get-value project (auto-detected)
#   GCP_ZONE                  default: us-central1-a  (free tier eligible)
#   GCP_MACHINE_TYPE          default: e2-micro        (free tier)
#   GCP_INSTANCE_NAME         default: streamforge-watch
#   GCP_DISK_SIZE_GB          default: 30              (free tier max)
#   GCP_REPO_URL              default: git remote get-url origin
#   GCP_REPO_BRANCH           default: current branch
#   SF_SAMPLE_SIZE            default: 400  (max safe for e2-micro, 1 GB RAM)
#   SF_WATCH_INTERVAL         default: 30   (seconds between drift poll cycles)
#   SF_WARMUP_CYCLES          default: 2
#   SF_NEW_CLUSTER_THRESHOLD  default: 0.12
#   SF_LOG_LEVEL              default: INFO
#
# COMMANDS:
#   up      Create VM, install StreamForge, run init + start watch (default)
#   down    Delete the VM (prompts for confirmation)
#   status  Show VM state, systemd unit status, last 20 watch log lines
#   logs    Tail watch.log live (Ctrl+C to stop)
#   ssh     Open an interactive SSH session
#
# EXTENDING FOR OTHER PROVIDERS:
#   This script is intentionally structured with labelled sections:
#     # ── PROVIDER: GCP ──
#     # ── REMOTE SETUP ──
#     # ── REMOTE START ──
#   To add EKS, EC2, Azure, etc., copy this file and replace the PROVIDER
#   section.  The REMOTE SETUP and REMOTE START sections are provider-agnostic
#   and can be reused as-is via SSH or cloud-init.
# =============================================================================
set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
_RED='\033[0;31m'; _GREEN='\033[0;32m'; _YELLOW='\033[1;33m'
_CYAN='\033[0;36m'; _DIM='\033[2m'; _RESET='\033[0m'

info()    { echo -e "${_CYAN}[deploy]${_RESET} $*"; }
success() { echo -e "${_GREEN}[deploy]${_RESET} $*"; }
warn()    { echo -e "${_YELLOW}[deploy]${_RESET} $*"; }
error()   { echo -e "${_RED}[deploy] ERROR:${_RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Command ────────────────────────────────────────────────────────────────────
COMMAND="${1:-up}"
[[ "$COMMAND" =~ ^(up|down|status|logs|ssh)$ ]] || die "Unknown command: $COMMAND. Use: up|down|status|logs|ssh"

# ── Prerequisites ──────────────────────────────────────────────────────────────
command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
command -v git    >/dev/null 2>&1 || die "git not found."

# ── Input resolution ───────────────────────────────────────────────────────────

# GCP parameters
GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$GCP_PROJECT" ]] || die "GCP_PROJECT is not set and 'gcloud config get-value project' returned nothing.\nRun: gcloud config set project YOUR_PROJECT_ID"

GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-micro}"
GCP_INSTANCE_NAME="${GCP_INSTANCE_NAME:-streamforge-watch}"
GCP_DISK_SIZE_GB="${GCP_DISK_SIZE_GB:-30}"

# Repo
GCP_REPO_URL="${GCP_REPO_URL:-$(git remote get-url origin 2>/dev/null || echo "")}"
[[ -n "$GCP_REPO_URL" ]] || die "GCP_REPO_URL is not set and 'git remote get-url origin' failed. Set GCP_REPO_URL explicitly."
GCP_REPO_BRANCH="${GCP_REPO_BRANCH:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"

# Kafka — required for 'up'
if [[ "$COMMAND" == "up" ]]; then
    if [[ -z "${KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
        echo -e "${_YELLOW}KAFKA_BOOTSTRAP_SERVERS is not set.${_RESET}"
        read -rp "  Enter Kafka bootstrap servers (host:port): " KAFKA_BOOTSTRAP_SERVERS
        [[ -n "$KAFKA_BOOTSTRAP_SERVERS" ]] || die "KAFKA_BOOTSTRAP_SERVERS is required."
    fi
fi
KAFKA_TOPIC="${KAFKA_TOPIC:-events.all}"

# LLM keys (optional — warn if missing)
GROQ_API_KEY="${GROQ_API_KEY:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [[ -z "$GROQ_API_KEY" && -z "$OPENROUTER_API_KEY" ]]; then
    warn "No LLM API key set (GROQ_API_KEY / OPENROUTER_API_KEY). streamforge init will use statistical fallback."
fi

# StreamForge tuning
SF_SAMPLE_SIZE="${SF_SAMPLE_SIZE:-400}"
SF_WATCH_INTERVAL="${SF_WATCH_INTERVAL:-30}"
SF_WARMUP_CYCLES="${SF_WARMUP_CYCLES:-2}"
SF_NEW_CLUSTER_THRESHOLD="${SF_NEW_CLUSTER_THRESHOLD:-0.12}"
SF_LOG_LEVEL="${SF_LOG_LEVEL:-INFO}"

# ── Shared SSH helper ──────────────────────────────────────────────────────────
_ssh() {
    gcloud compute ssh "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" \
        --project="$GCP_PROJECT" \
        --quiet \
        -- "$@"
}

_scp_to() {
    # _scp_to <local> <remote>
    gcloud compute scp \
        --zone="$GCP_ZONE" \
        --project="$GCP_PROJECT" \
        --quiet \
        "$1" "${GCP_INSTANCE_NAME}:$2"
}

# =============================================================================
# ── PROVIDER: GCP ──
# =============================================================================

_gcp_vm_exists() {
    gcloud compute instances describe "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --format="value(status)" 2>/dev/null | grep -q "RUNNING"
}

_gcp_create_vm() {
    info "Creating VM: $GCP_INSTANCE_NAME ($GCP_MACHINE_TYPE, $GCP_ZONE)"
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
        [[ $i -lt $max ]] || die "VM never became SSH-ready after $(( max * 5 )) seconds."
        echo -n "."
        sleep 5
    done
    echo ""
    success "SSH ready."
}

_gcp_delete_vm() {
    warn "This will PERMANENTLY DELETE instance: $GCP_INSTANCE_NAME ($GCP_ZONE)"
    read -rp "  Type the instance name to confirm: " confirm
    [[ "$confirm" == "$GCP_INSTANCE_NAME" ]] || die "Confirmation did not match. Aborting."
    gcloud compute instances delete "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" --quiet
    success "Instance deleted."
}

# =============================================================================
# ── REMOTE SETUP ──  (provider-agnostic, runs via SSH)
# =============================================================================
# Passed to the VM as a heredoc over stdin.
# Variables are expanded locally before transmission — intentional.

_remote_setup() {
    info "Installing system packages and StreamForge on the VM..."
    _ssh "bash -s" <<REMOTE_SETUP
set -euo pipefail

# ── System packages ──────────────────────────────────────────────────────────
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv tmux git logrotate 2>/dev/null

# ── 2 GB swap (critical on e2-micro / 1 GB RAM) ──────────────────────────────
if ! swapon --show | grep -q /swapfile; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap -q /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    echo "Swap: created 2 GB"
else
    echo "Swap: already configured"
fi

# ── Clone / update repo ───────────────────────────────────────────────────────
REPO_DIR="\$HOME/streamforge"
if [ -d "\$REPO_DIR/.git" ]; then
    echo "Repo exists — pulling latest ${GCP_REPO_BRANCH}..."
    git -C "\$REPO_DIR" fetch --quiet origin
    git -C "\$REPO_DIR" checkout --quiet "${GCP_REPO_BRANCH}"
    git -C "\$REPO_DIR" reset --quiet --hard "origin/${GCP_REPO_BRANCH}"
else
    echo "Cloning ${GCP_REPO_URL} (branch: ${GCP_REPO_BRANCH})..."
    git clone --quiet --branch "${GCP_REPO_BRANCH}" "${GCP_REPO_URL}" "\$REPO_DIR"
fi

# ── Python venv + install ─────────────────────────────────────────────────────
cd "\$REPO_DIR/streamforge-mvp"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
echo "StreamForge installed: \$(.venv/bin/python -m streamforge --version 2>/dev/null || echo ok)"

# ── Write .env ────────────────────────────────────────────────────────────────
mkdir -p logs
cat > .env.deploy <<ENV
KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}
KAFKA_TOPIC=${KAFKA_TOPIC}
GROQ_API_KEY=${GROQ_API_KEY}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
STREAMFORGE_LOG_LEVEL=${SF_LOG_LEVEL}
STREAMFORGE_LOG_DIR=logs
STREAMFORGE_NEW_CLUSTER_THRESHOLD=${SF_NEW_CLUSTER_THRESHOLD}
STREAMFORGE_WARMUP_CYCLES=${SF_WARMUP_CYCLES}
ENV
chmod 600 .env.deploy
echo ".env.deploy written."

# ── logrotate config ──────────────────────────────────────────────────────────
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
# ── REMOTE START ──  (provider-agnostic, runs via SSH)
# =============================================================================

_remote_init() {
    info "Running streamforge init (topic: $KAFKA_TOPIC, sample-size: $SF_SAMPLE_SIZE)..."
    _ssh "bash -s" <<REMOTE_INIT
set -euo pipefail
cd \$HOME/streamforge/streamforge-mvp
set -a; source .env.deploy; set +a

mkdir -p logs schemas
.venv/bin/python -m streamforge init "kafka://${KAFKA_TOPIC}" \
    --sample-size ${SF_SAMPLE_SIZE} \
    --output schemas \
    > logs/init.log 2>&1
echo "init exit: \$?"
tail -5 logs/init.log
REMOTE_INIT
    success "Schema inference complete → logs/init.log"
}

_remote_start_watch() {
    info "Installing and starting streamforge-watch systemd service..."
    _ssh "bash -s" <<REMOTE_WATCH
set -euo pipefail

REPO_DIR="\$HOME/streamforge/streamforge-mvp"
VENV="\$REPO_DIR/.venv/bin/python"
ENV_FILE="\$REPO_DIR/.env.deploy"
LOG_DIR="\$REPO_DIR/logs"

# Write systemd unit
sudo tee /etc/systemd/system/streamforge-watch.service >/dev/null <<UNIT
[Unit]
Description=StreamForge drift watch — ${KAFKA_TOPIC}
After=network.target

[Service]
Type=simple
User=\$USER
WorkingDirectory=\$REPO_DIR
EnvironmentFile=\$ENV_FILE
ExecStart=\$VENV -m streamforge watch kafka://${KAFKA_TOPIC} \\
          --interval ${SF_WATCH_INTERVAL} \\
          --sample-size 200
StandardOutput=append:\$LOG_DIR/watch.log
StandardError=append:\$LOG_DIR/watch.log
Restart=on-failure
RestartSec=15s
StartLimitBurst=5
StartLimitIntervalSec=120

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable streamforge-watch --quiet
sudo systemctl restart streamforge-watch

sleep 3
sudo systemctl status streamforge-watch --no-pager -l | head -20
REMOTE_WATCH
    success "streamforge-watch service started."
}

# =============================================================================
# ── COMMANDS ──
# =============================================================================

cmd_up() {
    echo ""
    echo -e "${_CYAN}══════════════════════════════════════════════════════${_RESET}"
    echo -e "${_CYAN}  StreamForge → GCP Compute Engine deployment${_RESET}"
    echo -e "${_CYAN}══════════════════════════════════════════════════════${_RESET}"
    echo -e "  Instance    : ${GCP_INSTANCE_NAME}"
    echo -e "  Machine     : ${GCP_MACHINE_TYPE}  (${GCP_ZONE})"
    echo -e "  Project     : ${GCP_PROJECT}"
    echo -e "  Kafka       : ${KAFKA_BOOTSTRAP_SERVERS}  →  ${KAFKA_TOPIC}"
    echo -e "  Sample size : ${SF_SAMPLE_SIZE}  (watch: 200)"
    echo -e "  Poll interval: ${SF_WATCH_INTERVAL}s  |  Warmup: ${SF_WARMUP_CYCLES} cycles"
    echo -e "  Repo        : ${GCP_REPO_URL}  (${GCP_REPO_BRANCH})"
    echo ""

    if _gcp_vm_exists; then
        warn "Instance '$GCP_INSTANCE_NAME' already exists and is RUNNING."
        read -rp "  Re-deploy to existing instance? [y/N] " yn
        [[ "$yn" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
    else
        _gcp_create_vm
    fi

    _remote_setup
    _remote_init
    _remote_start_watch

    echo ""
    echo -e "${_GREEN}══════════════════════════════════════════════════════${_RESET}"
    echo -e "${_GREEN}  Deployment complete${_RESET}"
    echo -e "${_GREEN}══════════════════════════════════════════════════════${_RESET}"
    echo ""
    echo "  Monitor logs:"
    echo "    bash deploy/gcp.sh logs"
    echo ""
    echo "  Check status:"
    echo "    bash deploy/gcp.sh status"
    echo ""
    echo "  SSH in:"
    echo "    bash deploy/gcp.sh ssh"
    echo ""
    echo "  Tear down:"
    echo "    bash deploy/gcp.sh down"
    echo ""
}

cmd_down() {
    _gcp_vm_exists || die "Instance '$GCP_INSTANCE_NAME' not found in $GCP_ZONE."
    _gcp_delete_vm
}

cmd_status() {
    _gcp_vm_exists || die "Instance '$GCP_INSTANCE_NAME' is not running."
    info "VM status:"
    gcloud compute instances describe "$GCP_INSTANCE_NAME" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --format="table(name, status, machineType.basename(), zone.basename(), networkInterfaces[0].accessConfigs[0].natIP)"
    echo ""
    info "Service + last 20 log lines:"
    _ssh "bash -s" <<'STATUS'
set -euo pipefail
echo "─── systemd ──────────────────────────────────────────────"
sudo systemctl status streamforge-watch --no-pager -l 2>&1 | head -15 || true
echo ""
echo "─── watch.log (last 20) ──────────────────────────────────"
tail -20 "$HOME/streamforge/streamforge-mvp/logs/watch.log" 2>/dev/null || echo "(no log yet)"
echo ""
echo "─── drift reports ────────────────────────────────────────"
ls -lht "$HOME/streamforge/streamforge-mvp/drift_reports/" 2>/dev/null || echo "(none)"
STATUS
}

cmd_logs() {
    _gcp_vm_exists || die "Instance '$GCP_INSTANCE_NAME' is not running."
    info "Streaming watch.log (Ctrl+C to stop)..."
    _ssh "tail -f \$HOME/streamforge/streamforge-mvp/logs/watch.log"
}

cmd_ssh() {
    _gcp_vm_exists || die "Instance '$GCP_INSTANCE_NAME' is not running."
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
