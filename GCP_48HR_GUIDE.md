# Running StreamForge on GCP Free Tier (48 hrs – 7 days)

## What This Guide Covers

**Runs on GCP (this guide):**
- `streamforge init` — one-shot schema inference
- `streamforge watch` — long-running drift monitor

**Stays wherever it already is (not touched here):**
- Kafka broker
- `demo/feed_all.py` producer

The GCP VM only needs outbound TCP to your `KAFKA_BOOTSTRAP_SERVERS` host. That is the only network dependency.

---

## Step 1 — Create the VM (5 minutes)

```bash
# From Cloud Shell or local gcloud CLI
gcloud compute instances create streamforge-watch \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB
```

> **Free tier:** 1 e2-micro/month in `us-central1`, `us-east1`, or `us-west1`. Stay in one of these three zones.

---

## Step 2 — SSH In and Install StreamForge

```bash
gcloud compute ssh streamforge-watch --zone=us-central1-a
```

Inside the VM:

```bash
sudo apt-get update -q
sudo apt-get install -y python3-pip python3-venv tmux git logrotate

git clone https://github.com/YOUR_USER/streamforge-mvp-full.git
cd streamforge-mvp-full/streamforge-mvp

python3 -m venv .venv
source .venv/bin/activate
pip install -e . -q
```

No Docker, no Kafka, no docker-compose needed on this VM.

---

## Step 3 — Configure the Only Required Setting

```bash
cp demo/.env demo/.env.local   # keep a local copy to edit
nano demo/.env.local
```

**The one thing you must change:**

```bash
# Point to your Kafka broker (not localhost)
KAFKA_BOOTSTRAP_SERVERS=YOUR_KAFKA_HOST:9092
```

Everything else can stay as-is:

```bash
GROQ_API_KEY=gsk_...           # needed only for streamforge init
STREAMFORGE_LOG_LEVEL=INFO
STREAMFORGE_LOG_DIR=logs
STREAMFORGE_NEW_CLUSTER_THRESHOLD=0.12
STREAMFORGE_WARMUP_CYCLES=2
```

Load the env before running commands:

```bash
set -a; source demo/.env.local; set +a
```

---

## Step 4 — Run Schema Inference (One-Shot)

> **Memory warning:** e2-micro has 1 GB RAM. Keep `--sample-size` at or below 400.

```bash
source .venv/bin/activate
set -a; source demo/.env.local; set +a

python -m streamforge init kafka://events.all \
  --sample-size 400 \
  --output schemas \
  2>&1 | tee logs/init.log
```

Inspect the result:

```bash
cat schemas/events.all/profile.yaml | grep -E "cluster_id|inference_confidence"
```

---

## Step 5 — Start the Watch in tmux

```bash
mkdir -p logs

tmux new-session -s forge -d   # create detached session

tmux send-keys -t forge \
  "source .venv/bin/activate && \
   set -a && source demo/.env.local && set +a && \
   python -m streamforge watch kafka://events.all \
     --interval 30 --sample-size 200 \
     >> logs/watch.log 2>&1" Enter
```

**Detach and leave running:** `Ctrl+B` then `D`

**Re-attach from any SSH session:**

```bash
gcloud compute ssh streamforge-watch --zone=us-central1-a
tmux attach -t forge
```

**Check it's alive without attaching:**

```bash
tmux list-sessions
tail -20 logs/watch.log
```

---

## Step 6 — Auto-Restart for Runs Longer Than 48 Hours

For 7-day runs, add a systemd service so the watch restarts automatically if it dies.

```bash
# Create the service file
sudo tee /etc/systemd/system/streamforge-watch.service > /dev/null <<EOF
[Unit]
Description=StreamForge drift watch
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/streamforge-mvp-full/streamforge-mvp
EnvironmentFile=$HOME/streamforge-mvp-full/streamforge-mvp/demo/.env.local
ExecStart=$HOME/streamforge-mvp-full/streamforge-mvp/.venv/bin/python \
          -m streamforge watch kafka://events.all \
          --interval 30 --sample-size 200
StandardOutput=append:$HOME/streamforge-mvp-full/streamforge-mvp/logs/watch.log
StandardError=append:$HOME/streamforge-mvp-full/streamforge-mvp/logs/watch.log
Restart=on-failure
RestartSec=15s

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable streamforge-watch
sudo systemctl start streamforge-watch
```

Check status:

```bash
sudo systemctl status streamforge-watch
journalctl -u streamforge-watch -f
```

> Use **either** the tmux approach (Step 5) **or** systemd (Step 6) — not both.

---

## Step 7 — Log Rotation (Prevents Disk Fill)

30 GB disappears quickly if logs run unrotated for 7 days. Set up daily rotation:

```bash
sudo tee /etc/logrotate.d/streamforge > /dev/null <<EOF
$HOME/streamforge-mvp-full/streamforge-mvp/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF

# Test the config
sudo logrotate -d /etc/logrotate.d/streamforge
```

`copytruncate` truncates the live file instead of moving it, so the running process keeps writing without needing a restart.

---

## Step 8 — Monitor and Collect Results

```bash
# Live drift feed
tail -f logs/watch.log

# Any drift reports generated
ls -lh drift_reports/events.all/ 2>/dev/null || echo "Clean — no drift reports yet"

# Quick connectivity check
python -m streamforge kafka-ping events.all
```

**Copy results back to your laptop:**

```bash
# From your local machine
gcloud compute scp --recurse \
  streamforge-watch:~/streamforge-mvp-full/streamforge-mvp/logs \
  ./logs-gcp --zone=us-central1-a

gcloud compute scp --recurse \
  streamforge-watch:~/streamforge-mvp-full/streamforge-mvp/drift_reports \
  ./drift-reports-gcp --zone=us-central1-a
```

---

## Step 9 — Stop and Clean Up

```bash
# Stop the VM (keeps disk, no compute charge)
gcloud compute instances stop streamforge-watch --zone=us-central1-a

# Delete entirely when done
gcloud compute instances delete streamforge-watch --zone=us-central1-a
```

---

## Cost Estimate

| Resource | Free Tier | 7-day usage |
|---|---|---|
| e2-micro compute | 744 hrs/month | 168 hrs — free |
| 30 GB persistent disk | 30 GB/month | 30 GB — free |
| Network egress | 1 GB/month | ~200 MB — free |
| Groq inference | 100 req/day free | 1 req total (init) — free |

**Total: $0** if you stay in `us-central1`, `us-east1`, or `us-west1`.

---

## Troubleshooting

**`streamforge kafka-ping` times out:**
- Check GCP firewall: your VM needs outbound TCP to the Kafka port (default 9092)
- Check your Kafka broker's firewall/security group allows inbound from the GCP VM's external IP (`curl ifconfig.me` on the VM to get it)

**Out of memory during `streamforge init`:**
```bash
# Add 2 GB swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Watch stopped and systemd hasn't restarted it yet:**
```bash
sudo systemctl restart streamforge-watch
sudo systemctl status streamforge-watch
```
