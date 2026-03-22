#!/usr/bin/env bash
# StreamForge demo — schema contract inference and drift detection
#
# Usage:
#   GROQ_API_KEY=gsk_... bash demo.sh
#
# What this demo shows:
#   Phase 1 — INFER:   Run init on three realistic streams. Produces schema.yaml + PII report.
#   Phase 2 — DECLARE: Inspect the git-committable contract artifact.
#   Phase 3 — DETECT:  Run plan against a drifted stream. Catches 3 classes of drift.
#   Phase 4 — REPORT:  Terminal schema view and drift history.
#   Phase 5 — WATCH:   Live continuous monitoring (10-second demo).

set -e

# ── colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"
CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
DIM="\033[2m"
RESET="\033[0m"

header()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}${CYAN}  $1${RESET}"; \
            echo -e "${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; }
step()    { echo -e "\n${BOLD}▶ $1${RESET}"; }
ok()      { echo -e "${GREEN}✓ $1${RESET}"; }
note()    { echo -e "${DIM}  $1${RESET}"; }
divider() { echo -e "${DIM}──────────────────────────────────────────${RESET}"; }

# ── preflight ─────────────────────────────────────────────────────────────────
if [ -z "$GROQ_API_KEY" ] && [ -z "$LLM_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
  echo -e "${RED}Error: no API key set.${RESET}"
  echo "  export GROQ_API_KEY=gsk_...   (free at https://console.groq.com)"
  echo "  or: LLM_API_KEY=... STREAMFORGE_BASE_URL=<endpoint> bash demo.sh"
  exit 1
fi

if ! command -v streamforge &>/dev/null; then
  echo -e "${RED}streamforge not found${RESET}"
  echo "  pip install -e ."
  exit 1
fi

echo -e "${DIM}API provider: Groq free tier (100k tokens/day)."
echo -e "StreamForge falls back to statistical inference automatically if rate-limited.${RESET}"
echo ""

# ── clean slate ───────────────────────────────────────────────────────────────
step "Cleaning previous run"
rm -rf schemas drift_reports
ok "schemas/ and drift_reports/ cleared"


# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 1 — INFER: Discover schema contracts from production data"
# ─────────────────────────────────────────────────────────────────────────────
note "StreamForge reads production events, discovers event families, infers field types and PII."
note "No schema was written in advance. The contract is inferred from the data."
echo ""

step "Payments stream — 300 events, multi-event-type, PII present"
streamforge init events/payments/stream_v1 --sample-size 300
divider

step "Bookings stream — 250 events, heavy PII (passport, DOB, loyalty number)"
streamforge init events/bookings/stream --sample-size 200
divider

step "IoT sensor stream — 500 events, sparse optional fields, mixed types"
streamforge init events/iot/stream --sample-size 200
divider

ok "Schema contracts written to schemas/"
echo ""
ls -1 schemas/


# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 2 — DECLARE: Inspect the git-committable contract"
# ─────────────────────────────────────────────────────────────────────────────
note "schema.yaml is the enforced contract. Human-editable. Reviewed in PRs."
note "profile.yaml is discovery metadata — all event families, routing field."
echo ""

step "Payments schema (schema.yaml — the enforced contract)"
cat schemas/stream_v1/schema.yaml
divider

step "Payments inference report — confidence per field, PII flags, ingest quality"
head -80 schemas/stream_v1/inference_report.md
divider

step "Stream policy — enforcement rules (alert/block thresholds)"
cat schemas/stream_v1/stream_policy.yaml


# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 3 — DETECT: Drift detection against the drifted stream"
# ─────────────────────────────────────────────────────────────────────────────
note "Scenario: a developer deployed at 2am. Three things changed:"
note "  1. 'amount' renamed to 'amount_minor_units' (dollars → integer cents)"
note "  2. Timestamp format changed: epoch_ms → ISO8601"
note "  3. 'card_last_four' appears — a PII field not in the baseline schema"
echo ""
note "Expected: Tier 3 (field removal + new PII) — plan exits 1"
echo ""

# plan exits 1 on Tier 3 with default policy — capture it so demo continues
streamforge plan events/payments/stream_v2_drift \
  --schema schemas/stream_v1/schema.yaml || PLAN_EXIT=$?

divider
REPORT=$(ls drift_reports/stream_v2_drift/*.md 2>/dev/null | sort | head -1)
if [ -n "$REPORT" ]; then
  step "Drift report written: $REPORT"
  cat "$REPORT"
fi

if [ "${PLAN_EXIT:-0}" -ne 0 ]; then
  echo -e "\n${RED}plan exited $PLAN_EXIT — Tier 3 drift detected, CI gate would block deploy${RESET}"
fi


# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 4 — REPORT: Schema and drift history"
# ─────────────────────────────────────────────────────────────────────────────

step "Payments — schema + drift history"
streamforge report events/payments/stream_v1
divider

step "Export payments schema to JSON Schema (Draft 2020-12)"
streamforge export schemas/stream_v1 --format json-schema
note "→ Can also export to Apache Avro: streamforge export schemas/stream_v1 --format avro"


# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 5 — WATCH: Continuous monitoring (10-second demo)"
# ─────────────────────────────────────────────────────────────────────────────
note "In production: runs as a daemon or sidecar. Rolling event window."
note "Window state persists to disk — survives restarts."
echo ""

streamforge watch events/payments/stream_v1 \
  --schema schemas/stream_v1/schema.yaml \
  --interval 5 &
WATCH_PID=$!
sleep 12
kill $WATCH_PID 2>/dev/null || true
wait $WATCH_PID 2>/dev/null || true


# ─────────────────────────────────────────────────────────────────────────────
header "Demo complete"
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_COUNT=$(ls schemas/ 2>/dev/null | wc -l | tr -d ' ')
REPORT_COUNT=$(find drift_reports -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

echo -e "Streams inferred:    ${GREEN}${SCHEMA_COUNT}${RESET}"
echo -e "Drift reports:       ${YELLOW}${REPORT_COUNT}${RESET}"
echo ""
echo -e "${DIM}Next steps:${RESET}"
echo -e "  CI gate:   streamforge plan events/payments/stream_v2_drift --schema schemas/stream_v1/schema.yaml"
echo -e "  Dashboard: streamforge ui"
echo -e "  No API:    streamforge demo  (synthetic events, no API key needed)"
echo ""
