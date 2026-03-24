#!/bin/bash
set -e

# Resolve brokers: input → env var → error
BROKERS="${INPUT_BROKERS:-${KAFKA_BOOTSTRAP_SERVERS:-}}"
if [ -z "$BROKERS" ]; then
  echo "::error::No Kafka brokers configured. Set KAFKA_BOOTSTRAP_SERVERS as a secret or pass brokers input."
  exit 1
fi

# Resolve API key
export GROQ_API_KEY="${INPUT_API_KEY:-${GROQ_API_KEY:-}}"

SCHEMA_DIR="${INPUT_SCHEMA_DIR:-schemas}"
MIN_TIER="${INPUT_MIN_TIER:-3}"
TOPIC="${INPUT_TOPIC:-}"

echo "::group::StreamForge CI Guardrail"
echo "Brokers:    ${BROKERS}"
echo "Schema dir: ${SCHEMA_DIR}"
echo "Min tier:   ${MIN_TIER}"

# Auto-discover topics from schemas/ directory if no topic specified
if [ -z "$TOPIC" ]; then
  echo "Topic: auto-discovering from ${SCHEMA_DIR}/"
  TOPICS=$(find "${SCHEMA_DIR}" -name "schema.yaml" -exec dirname {} \; 2>/dev/null | xargs -I{} basename {} | tr '\n' ' ' || true)
  if [ -z "$TOPICS" ]; then
    echo "::warning::No schemas found in ${SCHEMA_DIR}/. Run 'streamforge init kafka://your-topic' first."
    echo "drift-detected=false" >> "$GITHUB_OUTPUT"
    echo "highest-tier=none" >> "$GITHUB_OUTPUT"
    echo "::endgroup::"
    exit 0
  fi
  echo "Discovered topics: $TOPICS"
else
  TOPICS="$TOPIC"
fi
echo "::endgroup::"

OVERALL_EXIT=0

for T in $TOPICS; do
  SCHEMA_PATH="${SCHEMA_DIR}/${T}/schema.yaml"
  if [ ! -f "$SCHEMA_PATH" ]; then
    # Try with dots replaced by slashes for nested topic names
    T_SLASH=$(echo "$T" | tr '.' '/')
    SCHEMA_PATH="${SCHEMA_DIR}/${T_SLASH}/schema.yaml"
  fi
  if [ ! -f "$SCHEMA_PATH" ]; then
    echo "::warning::No schema for topic '${T}' — skipping"
    continue
  fi

  echo "::group::Checking ${T}"
  OUTPUT=$(streamforge plan "kafka://${T}" \
    --brokers "${BROKERS}" \
    --schema "${SCHEMA_PATH}" 2>&1) || PLAN_EXIT=$?
  PLAN_EXIT="${PLAN_EXIT:-0}"
  echo "${OUTPUT}"
  echo "::endgroup::"

  if [ "${PLAN_EXIT}" -ne 0 ]; then
    OVERALL_EXIT=1
    echo "drift-detected=true" >> "$GITHUB_OUTPUT"
    echo "highest-tier=${MIN_TIER}" >> "$GITHUB_OUTPUT"

    # Post PR comment if GitHub token available
    if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_EVENT_NUMBER:-}" ]; then
      BODY="## ⚠️ StreamForge: Breaking Change Detected on \`${T}\`\n\n\`\`\`\n${OUTPUT}\n\`\`\`\n\n*Run \`streamforge plan kafka://${T}\` locally to investigate.*"
      curl -sf -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"body\": \"${BODY}\"}" \
        "${GITHUB_API_URL}/repos/${GITHUB_REPOSITORY}/issues/${GITHUB_EVENT_NUMBER}/comments" > /dev/null || true
    fi

    echo "::error::Breaking change detected on ${T} — merge blocked"
  fi
done

if [ "$OVERALL_EXIT" -eq 0 ]; then
  echo "drift-detected=false" >> "$GITHUB_OUTPUT"
  echo "highest-tier=none" >> "$GITHUB_OUTPUT"
  echo "::notice::All schema checks passed — no breaking changes detected"
fi

exit "$OVERALL_EXIT"
