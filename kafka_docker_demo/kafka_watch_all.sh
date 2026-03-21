#!/usr/bin/env bash
# kafka_watch_all.sh — Watch all Kafka topics for drift in parallel
# Usage: ./kafka_docker_demo/kafka_watch_all.sh [env] [brokers]
#
# Arguments:
#   env     Config environment: dev | staging | prod  (default: dev)
#   brokers Kafka broker list                         (default: localhost:9092)
#
# Examples:
#   ./kafka_docker_demo/kafka_watch_all.sh
#   ./kafka_docker_demo/kafka_watch_all.sh dev localhost:9092
#   ./kafka_docker_demo/kafka_watch_all.sh prod kafka-prod:9092
#
# Per-topic config is loaded from config/topics/<topic>.yaml.
# Env-level config is loaded from config/<env>.yaml.
# Both override config/default.yaml.

set -euo pipefail

ENV="${1:-${STREAMFORGE_ENV:-dev}}"
BROKERS="${2:-${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}}"

TOPICS=(
  events.payments
  events.bookings
  events.iot
  events.flights
  events.github
  events.wikipedia
)

export STREAMFORGE_ENV="$ENV"
export KAFKA_BOOTSTRAP_SERVERS="$BROKERS"

echo "StreamForge — watching ${#TOPICS[@]} Kafka topics"
echo "  env:     $ENV"
echo "  brokers: $BROKERS"
echo ""

pids=()

for topic in "${TOPICS[@]}"; do
  streamforge watch "kafka://$topic" \
    --brokers "$BROKERS" \
    --env "$ENV" &
  pid=$!
  pids+=("$pid")
  echo "✓  Started: $topic  (PID $pid, env: $ENV)"
done

echo ""
echo "Watching ${#pids[@]} topics. Press Ctrl+C to stop all."

trap 'echo ""; echo "Stopping all watchers..."; kill 0' INT TERM

wait
