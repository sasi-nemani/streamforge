#!/usr/bin/env bash
# =============================================================================
# deploy/two-vm.sh — 2-VM GCP deployment for StreamForge demos
#
# Architecture:
#   sf-kafka  (e2-small, 2GB) — Docker + Confluent Kafka KRaft + feed_all.py
#   sf-app    (e2-micro, 1GB) — StreamForge watch/init/demo/UI
#
# Both VMs live in the same VPC — internal networking, no ngrok, no tunnels.
#
# USAGE:
#   bash deploy/two-vm.sh up        # Create both VMs, install everything
#   bash deploy/two-vm.sh down      # Delete both VMs
#   bash deploy/two-vm.sh status    # Show VM state, Kafka health, watch status
#   bash deploy/two-vm.sh ssh-kafka # SSH into Kafka VM
#   bash deploy/two-vm.sh ssh-app   # SSH into StreamForge VM
#   bash deploy/two-vm.sh demo      # Print demo run sheet
#   bash deploy/two-vm.sh inject    # Inject drift into live payments stream
#
# REQUIRED ENV VARS (or set in deploy/.env):
#   GROQ_API_KEY          — free at console.groq.com (primary LLM)
#
# OPTIONAL:
#   GCP_PROJECT           — default: loonstreamforge
#   GCP_ZONE              — default: us-central1-a (free tier)
#   KAFKA_TOPICS          — default: events.payments,events.bookings,events.iot,events.wiki
#
# COST:  ~$16/month ($0.53/day)
#   sf-kafka  e2-small  $14.22/mo
#   sf-app    e2-micro  $0.00/mo  (free tier — 1 per billing account)
#   Disks     2x 20GB   $1.60/mo
#   Total 60 days:      ~$31.64 of $100 budget
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Load deploy/.env if present ──────────────────────────────────────────────
[[ -f "$SCRIPT_DIR/.env" ]] && { set -a; source "$SCRIPT_DIR/.env"; set +a; }
[[ -f "$REPO_ROOT/demo/.env" ]] && { set -a; source "$REPO_ROOT/demo/.env"; set +a; }

# ── Colors ───────────────────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'
B='\033[1m'; D='\033[2m'; X='\033[0m'
info()    { echo -e "${C}[deploy]${X} $*"; }
ok()      { echo -e "${G}[deploy]${X} $*"; }
warn()    { echo -e "${Y}[deploy]${X} $*"; }
err()     { echo -e "${R}[deploy] ERROR:${X} $*" >&2; }
die()     { err "$*"; exit 1; }

# ── Config ───────────────────────────────────────────────────────────────────
GCP_PROJECT="${GCP_PROJECT:-loonstreamforge}"
GCP_ZONE="${GCP_ZONE:-us-central1-c}"  # us-central1-a often exhausted

KAFKA_VM="sf-kafka"
KAFKA_MACHINE="e2-small"     # 2 vCPU, 2GB — fits JVM Kafka + feed_all.py
KAFKA_DISK="20"

APP_VM="sf-app"
APP_MACHINE="${APP_MACHINE:-e2-small}"  # e2-small (2GB) — reliable availability
APP_DISK="20"

KAFKA_TOPICS="${KAFKA_TOPICS:-events.payments,events.bookings,events.iot,events.wiki}"
GROQ_API_KEY="${GROQ_API_KEY:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

# StreamForge tuning
SF_SAMPLE_SIZE="${SF_SAMPLE_SIZE:-400}"
SF_WATCH_INTERVAL="${SF_WATCH_INTERVAL:-30}"
SF_WARMUP_CYCLES="${SF_WARMUP_CYCLES:-10}"
SF_LOG_LEVEL="${SF_LOG_LEVEL:-INFO}"

# Event rates (events/sec per topic)
PAYMENT_RATE="${PAYMENT_RATE:-2}"
BOOKING_RATE="${BOOKING_RATE:-1}"
IOT_RATE="${IOT_RATE:-5}"
WIKI_RATE="${WIKI_RATE:-1}"

COMMAND="${1:-up}"

# ── Prerequisites ────────────────────────────────────────────────────────────
command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found"

# ── Helper: wait for SSH ─────────────────────────────────────────────────────
_wait_ssh() {
    local vm="$1"
    info "Waiting for $vm SSH..."
    for i in $(seq 1 30); do
        if gcloud compute ssh "$vm" --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
            --command="echo ok" 2>/dev/null | grep -q ok; then
            return 0
        fi
        sleep 5
        [[ $((i % 4)) -eq 0 ]] && info "  still waiting... (${i}×5s)"
    done
    die "$vm SSH not ready after 150s"
}

# ── Helper: run on VM ────────────────────────────────────────────────────────
_run() {
    local vm="$1"; shift
    gcloud compute ssh "$vm" --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --command="$*" 2>&1
}

# ── Helper: get internal IP ──────────────────────────────────────────────────
_internal_ip() {
    gcloud compute instances describe "$1" \
        --zone="$GCP_ZONE" --project="$GCP_PROJECT" \
        --format="get(networkInterfaces[0].networkIP)" 2>/dev/null
}

# =============================================================================
# COMMAND: up
# =============================================================================
_cmd_up() {
    echo ""
    echo -e "${B}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "${B}${C}  StreamForge — 2-VM GCP Deployment${X}"
    echo -e "${B}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo ""

    # ── Step 1: Create VMs ───────────────────────────────────────────────
    info "Creating VMs..."

    local machine disk tarball kafka_ext_ip app_ext_ip
    for vm_name in "$KAFKA_VM" "$APP_VM"; do
        if gcloud compute instances describe "$vm_name" --zone="$GCP_ZONE" \
            --project="$GCP_PROJECT" &>/dev/null; then
            warn "  $vm_name already exists — skipping creation"
            gcloud compute instances start "$vm_name" --zone="$GCP_ZONE" \
                --project="$GCP_PROJECT" 2>/dev/null || true
        else
            if [[ "$vm_name" == "$KAFKA_VM" ]]; then
                machine="$KAFKA_MACHINE"; disk="$KAFKA_DISK"
            else
                machine="$APP_MACHINE"; disk="$APP_DISK"
            fi
            gcloud compute instances create "$vm_name" \
                --zone="$GCP_ZONE" \
                --project="$GCP_PROJECT" \
                --machine-type="$machine" \
                --boot-disk-size="${disk}GB" \
                --boot-disk-type=pd-standard \
                --image-family=debian-12 \
                --image-project=debian-cloud \
                --tags=streamforge \
                --metadata=startup-script='#!/bin/bash
                    apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip docker.io docker-compose curl tmux > /dev/null 2>&1
                    systemctl enable docker && systemctl start docker
                    usermod -aG docker $(ls /home/ | head -1) 2>/dev/null || true
                ' \
                2>&1
            ok "  $vm_name created ($machine)"
        fi
    done

    # Wait for both VMs to be SSH-ready
    _wait_ssh "$KAFKA_VM"
    _wait_ssh "$APP_VM"

    KAFKA_IP=$(_internal_ip "$KAFKA_VM")
    APP_IP=$(_internal_ip "$APP_VM")
    info "Internal IPs: kafka=$KAFKA_IP  app=$APP_IP"

    # ── Step 2: Upload code to both VMs ──────────────────────────────────
    info "Uploading code..."

    # Create tarball (exclude heavy/unnecessary dirs)
    tarball="/tmp/sf-deploy-$$.tar.gz"
    tar czf "$tarball" \
        --exclude='.git' --exclude='__pycache__' --exclude='.streamforge' \
        --exclude='mainSite' --exclude='*.pyc' --exclude='.venv' \
        --exclude='schemas' --exclude='drift_reports' --exclude='logs' \
        --exclude='node_modules' \
        -C "$(dirname "$REPO_ROOT")" \
        "$(basename "$REPO_ROOT")" 2>/dev/null

    for vm in "$KAFKA_VM" "$APP_VM"; do
        gcloud compute scp "$tarball" "$vm:/tmp/sf-deploy.tar.gz" \
            --zone="$GCP_ZONE" --project="$GCP_PROJECT" 2>/dev/null
    done
    rm -f "$tarball"
    ok "  Code uploaded to both VMs"

    # ── Step 3: Setup Kafka VM ───────────────────────────────────────────
    info "Setting up $KAFKA_VM (Confluent Kafka KRaft + feed_all.py)..."

    _run "$KAFKA_VM" "bash -s" <<'KAFKA_SETUP'
set -e
cd /tmp
tar xzf sf-deploy.tar.gz 2>/dev/null
rm -rf ~/streamforge
mv streamforge-mvp ~/streamforge

# Wait for Docker
for i in $(seq 1 30); do
    docker info &>/dev/null && break
    sleep 2
done

# Create Kafka docker-compose for GCP (single listener, no ngrok needed)
INTERNAL_IP=$(hostname -I | awk '{print $1}')

mkdir -p ~/kafka
cat > ~/kafka/docker-compose.yml <<EOF
services:
  kafka:
    image: confluentinc/cp-kafka:7.6.0
    hostname: kafka
    container_name: sf-kafka
    restart: unless-stopped
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://${INTERNAL_IP}:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_LOG_RETENTION_HOURS: 6
      KAFKA_LOG_RETENTION_BYTES: 536870912
      KAFKA_HEAP_OPTS: "-Xmx512m -Xms512m"
      CLUSTER_ID: "MkU3OEVBNTcwNTJENDM2Qk"
    volumes:
      - kafka-data:/var/lib/kafka/data
    healthcheck:
      test: ["CMD", "kafka-broker-api-versions", "--bootstrap-server", "localhost:9092"]
      interval: 10s
      timeout: 10s
      retries: 15

volumes:
  kafka-data:
EOF

cd ~/kafka

# Install docker compose plugin if not available
if ! docker compose version &>/dev/null; then
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

docker compose up -d

echo "Waiting for Kafka to be healthy..."
for i in $(seq 1 30); do
    status=$(docker inspect --format='{{.State.Health.Status}}' sf-kafka 2>/dev/null || echo "starting")
    [ "$status" = "healthy" ] && break
    sleep 5
done

docker inspect --format='{{.State.Health.Status}}' sf-kafka

# Install Python deps for feed_all.py
python3 -m venv ~/venv 2>/dev/null || true
~/venv/bin/pip install kafka-python-ng httpx 2>&1 | tail -3

echo "KAFKA_SETUP_DONE"
KAFKA_SETUP

    ok "  Kafka running on $KAFKA_VM"

    # ── Step 4: Start feed_all.py on Kafka VM ────────────────────────────
    info "Starting event producers on $KAFKA_VM..."

    _run "$KAFKA_VM" "bash -s" <<FEED_SCRIPT
set -e
INTERNAL_IP=\$(hostname -I | awk '{print \$1}')
mkdir -p ~/streamforge/logs

# Kill any existing feed
pkill -f feed_all.py 2>/dev/null || true
sleep 1

# Preseed 500 events then go live
nohup ~/venv/bin/python3 ~/streamforge/demo/feed_all.py \
    --brokers "\${INTERNAL_IP}:9092" \
    --preseed 500 \
    --payment-rate $PAYMENT_RATE \
    --booking-rate $BOOKING_RATE \
    --iot-rate $IOT_RATE \
    --wiki-rate $WIKI_RATE \
    >> ~/streamforge/logs/producer.log 2>&1 &

echo "Feed PID: \$!"
sleep 3

# Verify events are flowing
~/venv/bin/python3 -c "
from kafka import KafkaConsumer
c = KafkaConsumer(bootstrap_servers='\${INTERNAL_IP}:9092', consumer_timeout_ms=5000, auto_offset_reset='latest')
topics = c.topics()
c.close()
print(f'Topics visible: {sorted(topics)}')
" 2>&1
echo "FEED_STARTED"
FEED_SCRIPT

    ok "  Event producers running"

    # ── Step 5: Setup StreamForge VM ─────────────────────────────────────
    info "Setting up $APP_VM (StreamForge)..."

    _run "$APP_VM" "bash -s" <<'APP_SETUP'
set -e
cd /tmp
tar xzf sf-deploy.tar.gz 2>/dev/null
rm -rf ~/streamforge
mv streamforge-mvp ~/streamforge
cd ~/streamforge

# Create venv and install StreamForge
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -e "." kafka-python-ng 2>&1 | tail -5

# Verify CLI works
.venv/bin/python3 -m streamforge --help | head -3

mkdir -p logs schemas drift_reports
echo "APP_SETUP_DONE"
APP_SETUP

    ok "  StreamForge installed on $APP_VM"

    # ── Step 6: Write .env on App VM ─────────────────────────────────────
    info "Configuring StreamForge..."

    _run "$APP_VM" "cat > ~/streamforge/.env.deploy" <<ENV_FILE
KAFKA_BOOTSTRAP_SERVERS=${KAFKA_IP}:9092
GROQ_API_KEY=${GROQ_API_KEY}
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
STREAMFORGE_LOG_LEVEL=${SF_LOG_LEVEL}
STREAMFORGE_LOG_DIR=logs
STREAMFORGE_WARMUP_CYCLES=${SF_WARMUP_CYCLES}
STREAMFORGE_NEW_CLUSTER_THRESHOLD=0.12
ENV_FILE

    # ── Step 7: Init schemas on App VM ───────────────────────────────────
    info "Initializing schemas (this takes 1-2 minutes per topic)..."

    IFS=',' read -ra TOPICS <<< "$KAFKA_TOPICS"
    for topic in "${TOPICS[@]}"; do
        info "  Inferring schema for $topic..."
        _run "$APP_VM" "bash -s" <<INIT_TOPIC
set -e
cd ~/streamforge
set -a; source .env.deploy 2>/dev/null; set +a
export PATH=~/streamforge/.venv/bin:\$PATH

# Wait for enough events
for attempt in \$(seq 1 20); do
    count=\$(python3 -c "
from kafka import KafkaConsumer, TopicPartition
c = KafkaConsumer(bootstrap_servers='\${KAFKA_BOOTSTRAP_SERVERS}', consumer_timeout_ms=3000)
tp = TopicPartition('$topic', 0)
c.assign([tp])
c.seek_to_end(tp)
print(c.position(tp))
c.close()
" 2>/dev/null || echo 0)
    [ "\$count" -ge 100 ] && break
    sleep 5
done

python3 -m streamforge init "kafka://$topic" \
    --brokers "\${KAFKA_BOOTSTRAP_SERVERS}" \
    --sample-size $SF_SAMPLE_SIZE \
    --output schemas \
    2>&1 | tail -10
INIT_TOPIC
        ok "  $topic: schema inferred"
    done

    # ── Step 8: Start watch services on App VM ───────────────────────────
    info "Starting drift watchers..."

    for topic in "${TOPICS[@]}"; do
        local slug="${topic//./-}"
        _run "$APP_VM" "bash -s" <<WATCH_SVC
# Create systemd service for this topic
sudo tee /etc/systemd/system/streamforge-watch-${slug}.service > /dev/null <<UNIT
[Unit]
Description=StreamForge watch — ${topic}
After=network.target

[Service]
Type=simple
User=\$(whoami)
WorkingDirectory=/home/\$(whoami)/streamforge
EnvironmentFile=/home/\$(whoami)/streamforge/.env.deploy
ExecStart=/home/\$(whoami)/streamforge/.venv/bin/python -m streamforge watch kafka://${topic} --interval ${SF_WATCH_INTERVAL} --sample-size 200
StandardOutput=append:/home/\$(whoami)/streamforge/logs/watch_${slug}.log
StandardError=append:/home/\$(whoami)/streamforge/logs/watch_${slug}.log
Restart=on-failure
RestartSec=15s

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable streamforge-watch-${slug}
sudo systemctl start streamforge-watch-${slug}
WATCH_SVC
        ok "  Watch started: $topic"
    done

    # ── Summary ──────────────────────────────────────────────────────────
    kafka_ext_ip=$(gcloud compute instances describe "$KAFKA_VM" --zone="$GCP_ZONE" \
        --project="$GCP_PROJECT" --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)
    app_ext_ip=$(gcloud compute instances describe "$APP_VM" --zone="$GCP_ZONE" \
        --project="$GCP_PROJECT" --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null)

    echo ""
    echo -e "${B}${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "${B}${G}  StreamForge deployed${X}"
    echo -e "${B}${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo ""
    echo -e "  ${B}Kafka VM${X}       $KAFKA_VM ($KAFKA_MACHINE)"
    echo -e "    Internal:    ${B}${KAFKA_IP}:9092${X}"
    echo -e "    External:    ${B}${kafka_ext_ip}${X}"
    echo -e "    SSH:         ${D}gcloud compute ssh $KAFKA_VM --zone=$GCP_ZONE --project=$GCP_PROJECT${X}"
    echo ""
    echo -e "  ${B}App VM${X}         $APP_VM ($APP_MACHINE)"
    echo -e "    Internal:    ${B}${APP_IP}${X}"
    echo -e "    External:    ${B}${app_ext_ip}${X}"
    echo -e "    SSH:         ${D}gcloud compute ssh $APP_VM --zone=$GCP_ZONE --project=$GCP_PROJECT${X}"
    echo ""
    echo -e "  ${B}Topics:${X}        ${KAFKA_TOPICS}"
    echo -e "  ${B}Event rates:${X}   pay=${PAYMENT_RATE}/s  book=${BOOKING_RATE}/s  iot=${IOT_RATE}/s  wiki=${WIKI_RATE}/s"
    echo ""
    echo -e "  ${B}${Y}Run the demo:${X}"
    echo -e "    ${B}bash deploy/two-vm.sh demo${X}"
    echo ""
}

# =============================================================================
# COMMAND: down
# =============================================================================
_cmd_down() {
    echo ""
    echo -e "${Y}This will DELETE both VMs and all data on them.${X}"
    read -rp "Continue? (y/N) " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { echo "Cancelled."; exit 0; }

    for vm in "$KAFKA_VM" "$APP_VM"; do
        if gcloud compute instances describe "$vm" --zone="$GCP_ZONE" \
            --project="$GCP_PROJECT" &>/dev/null; then
            gcloud compute instances delete "$vm" --zone="$GCP_ZONE" \
                --project="$GCP_PROJECT" --quiet 2>&1
            ok "Deleted $vm"
        else
            info "$vm does not exist"
        fi
    done
}

# =============================================================================
# COMMAND: status
# =============================================================================
_cmd_status() {
    echo ""
    echo -e "${B}${C}  StreamForge — Status${X}"
    echo ""

    # VM status
    gcloud compute instances list --project="$GCP_PROJECT" \
        --filter="name~'^sf-'" \
        --format="table(name,machineType.basename(),zone,status,networkInterfaces[0].accessConfigs[0].natIP)" 2>&1

    KAFKA_IP=$(_internal_ip "$KAFKA_VM" 2>/dev/null || echo "")
    if [[ -z "$KAFKA_IP" ]]; then
        warn "Kafka VM not found. Run: bash deploy/two-vm.sh up"
        return
    fi

    echo ""
    info "Kafka health:"
    _run "$KAFKA_VM" "docker inspect --format='{{.State.Health.Status}}' sf-kafka 2>/dev/null || echo 'not running'" || true

    echo ""
    info "Event producer:"
    _run "$KAFKA_VM" "pgrep -fa feed_all.py || echo 'not running'" || true

    echo ""
    info "Topic offsets:"
    _run "$KAFKA_VM" "docker exec sf-kafka kafka-run-class kafka.tools.GetOffsetShell \
        --broker-list localhost:9092 --topic-partitions '.*:0' 2>/dev/null | head -10" || true

    echo ""
    info "StreamForge watchers:"
    _run "$APP_VM" "systemctl list-units 'streamforge-watch-*' --no-pager 2>/dev/null" || true

    echo ""
    info "Schemas:"
    _run "$APP_VM" "ls ~/streamforge/schemas/ 2>/dev/null || echo 'none'" || true

    echo ""
    info "Drift reports:"
    _run "$APP_VM" "for d in ~/streamforge/drift_reports/*/; do
        name=\$(basename \"\$d\" 2>/dev/null)
        count=\$(ls \"\$d\"/*.md 2>/dev/null | wc -l)
        [ \"\$count\" -gt 0 ] && echo \"  \$name: \$count reports\"
    done" || true
}

# =============================================================================
# COMMAND: ssh-kafka / ssh-app
# =============================================================================
_cmd_ssh_kafka() {
    gcloud compute ssh "$KAFKA_VM" --zone="$GCP_ZONE" --project="$GCP_PROJECT"
}
_cmd_ssh_app() {
    gcloud compute ssh "$APP_VM" --zone="$GCP_ZONE" --project="$GCP_PROJECT"
}

# =============================================================================
# COMMAND: inject  — trigger drift on the live payments stream
# =============================================================================
_cmd_inject() {
    KAFKA_IP=$(_internal_ip "$KAFKA_VM")
    info "Injecting drift into events.payments via $APP_VM..."
    _run "$APP_VM" "cd ~/streamforge && \
        .venv/bin/python3 demo/inject_drift.py --brokers ${KAFKA_IP}:9092 --count 50 2>&1"
    ok "Drift injected. Watch for TIER 3 alerts in the next watch cycle (${SF_WATCH_INTERVAL}s)."
}

# =============================================================================
# COMMAND: demo  — print the demo run sheet
# =============================================================================
_cmd_demo() {
    local app_ext_ip
    app_ext_ip=$(gcloud compute instances describe "$APP_VM" --zone="$GCP_ZONE" \
        --project="$GCP_PROJECT" --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null || echo "<app-ip>")

    echo ""
    echo -e "${B}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo -e "${B}${C}  StreamForge Demo — Run Sheet${X}"
    echo -e "${B}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo ""
    echo -e "  ${B}Step 0: Check everything is running${X}"
    echo -e "    ${D}bash deploy/two-vm.sh status${X}"
    echo ""
    echo -e "  ${B}Step 1: SSH into the StreamForge VM${X}"
    echo -e "    ${B}gcloud compute ssh $APP_VM --zone=$GCP_ZONE --project=$GCP_PROJECT${X}"
    echo ""
    echo -e "  ${B}Step 2: Run the demo for your audience${X}"
    echo ""
    echo -e "    ${G}For the CTO (90 seconds):${X}"
    echo -e "      cd ~/streamforge && .venv/bin/python3 -m streamforge demo --cto"
    echo ""
    echo -e "    ${G}For engineering directors (5 minutes):${X}"
    echo -e "      cd ~/streamforge && .venv/bin/python3 -m streamforge demo --eng"
    echo ""
    echo -e "    ${G}For business / investors (visual dashboard):${X}"
    echo -e "      cd ~/streamforge && .venv/bin/python3 -m streamforge ui --port 8501"
    echo -e "      ${D}Then in another terminal:${X}"
    echo -e "      gcloud compute ssh $APP_VM --zone=$GCP_ZONE --project=$GCP_PROJECT -- -L 8501:localhost:8501"
    echo -e "      ${D}Open: http://localhost:8501${X}"
    echo ""
    echo -e "  ${B}Step 3: Show live drift detection (the wow moment)${X}"
    echo ""
    echo -e "    ${D}In one terminal — show the watch loop:${X}"
    echo -e "      .venv/bin/python3 -m streamforge watch kafka://events.payments \\"
    echo -e "        --brokers \$(cat .env.deploy | grep KAFKA | cut -d= -f2) --interval 10"
    echo ""
    echo -e "    ${D}In another terminal — inject breaking changes:${X}"
    echo -e "      ${B}bash deploy/two-vm.sh inject${X}"
    echo ""
    echo -e "    ${D}Watch the terminal light up with TIER 3 alerts in ~10 seconds.${X}"
    echo ""
    echo -e "  ${B}Step 4: Show the CI gate${X}"
    echo -e "    .venv/bin/python3 -m streamforge plan kafka://events.payments \\"
    echo -e "      --brokers \$(cat .env.deploy | grep KAFKA | cut -d= -f2)"
    echo -e "    ${D}Exit code 1 = deploy blocked.${X}"
    echo ""
    echo -e "${B}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
    echo ""
}

# =============================================================================
# Route command
# =============================================================================
case "$COMMAND" in
    up)        _cmd_up ;;
    down)      _cmd_down ;;
    status)    _cmd_status ;;
    ssh-kafka) _cmd_ssh_kafka ;;
    ssh-app)   _cmd_ssh_app ;;
    inject)    _cmd_inject ;;
    demo)      _cmd_demo ;;
    *)         die "Unknown command: $COMMAND. Use: up|down|status|ssh-kafka|ssh-app|inject|demo" ;;
esac
