#!/usr/bin/env bash
# watch_all.sh — Run streamforge watch on all streams in parallel
# Usage: ./scripts/watch_all.sh [interval_seconds] [sample_size]
#
# Defaults: 300s interval, 200 samples. Examples:
#   ./scripts/watch_all.sh          # 5 min, 200 samples
#   ./scripts/watch_all.sh 300 100  # 5 min, 100 samples
#   ./scripts/watch_all.sh 60  50   # 1 min, 50 samples (testing)

set -euo pipefail

INTERVAL="${1:-300}"
SAMPLE_SIZE="${2:-200}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

STREAMS=(
  events/bookings/stream
  events/flights/stream
  events/iot/stream
  events/payments/stream_v1
  events/github/push
  events/wikipedia/live
)

pids=()

for stream in "${STREAMS[@]}"; do
  stream_path="$REPO_ROOT/$stream"
  if [[ ! -d "$stream_path" ]]; then
    echo "⚠  Skipping $stream — directory not found"
    continue
  fi

  streamforge watch "$stream_path" --interval "$INTERVAL" --sample-size "$SAMPLE_SIZE" &
  pid=$!
  pids+=("$pid")
  echo "✓  Started: $stream (PID $pid, interval ${INTERVAL}s, sample ${SAMPLE_SIZE})"
done

echo ""
echo "Watching ${#pids[@]} streams. Press Ctrl+C to stop all."

# Kill all child processes on exit
trap 'echo ""; echo "Stopping all watchers..."; kill 0' INT TERM

wait
