#!/usr/bin/env bash
# StreamForge Demo — Cleanup
# Tears down Docker containers, volumes, and generated output.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Fix: kill lingering background processes before tearing down Docker.
# Without this, feed_all.py and watch processes survive the cleanup and can
# auto-create the Kafka topic (1 partition) before setup.sh runs, causing the
# "wrong partition count" bug on the next setup run.
echo "Stopping background StreamForge processes..."
pkill -f "demo/feed_all.py"      2>/dev/null || true
pkill -f "streamforge watch"     2>/dev/null || true
pkill -f "streamforge kafka-ping" 2>/dev/null || true
sleep 1   # give processes a moment to exit cleanly

echo "Stopping and removing Docker containers..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v --remove-orphans

echo "Removing generated output..."
rm -rf schemas/events.all drift_reports/events.all

echo "✓ Cleanup complete. Run setup.sh to start fresh."
