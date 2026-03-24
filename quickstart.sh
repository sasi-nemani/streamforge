#!/usr/bin/env bash
# StreamForge — 5-minute quickstart
# Usage: bash quickstart.sh
set -euo pipefail

BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
TOPIC="${STREAMFORGE_TOPIC:-events.all}"

echo ""
echo "StreamForge Quickstart"
echo "══════════════════════"
echo ""

# 1. Install
echo "Step 1: Installing StreamForge..."
pip install streamforge-cli -q

# 2. Check connectivity
echo "Step 2: Checking Kafka connectivity..."
streamforge kafka-ping "$TOPIC" --brokers "$BROKERS" --timeout 10

# 3. Discover
echo "Step 3: Your current governance posture..."
streamforge discover --brokers "$BROKERS"

# 4. Infer schema
echo "Step 4: Inferring schema for $TOPIC..."
streamforge init "kafka://$TOPIC" --brokers "$BROKERS"

# 5. One-shot drift check
echo "Step 5: Running drift check..."
streamforge plan "kafka://$TOPIC" --brokers "$BROKERS" && \
  echo "No drift detected" || \
  echo "Drift detected — see above"

echo ""
echo "Done! Next: run 'streamforge watch kafka://$TOPIC --brokers $BROKERS' for continuous monitoring."
