#!/usr/bin/env bash
# StreamForge demo — runs the full pipeline across three streams
# Usage: GROQ_API_KEY=gsk_... bash demo.sh

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
warn()    { echo -e "${YELLOW}⚠ $1${RESET}"; }
divider() { echo -e "${DIM}──────────────────────────────────────────${RESET}"; }

# ── preflight ─────────────────────────────────────────────────────────────────
if [ -z "$GROQ_API_KEY" ] && [ -z "$LLM_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
  echo -e "${RED}Error: no API key set.${RESET}"
  echo "  export GROQ_API_KEY=gsk_..."
  echo "  or pass a different provider key via LLM_API_KEY / OPENAI_API_KEY"
  exit 1
fi

if ! command -v streamforge &>/dev/null; then
  echo -e "${RED}streamforge not found — run: pip install -e .${RESET}"
  exit 1
fi

echo -e "${DIM}Note: Groq free tier — 100k tokens/day, 12k tokens/minute."
echo -e "If LLM rate-limits are hit, StreamForge falls back to statistical"
echo -e "inference automatically (lower confidence, no field descriptions).${RESET}"
echo ""

# ── clean slate ───────────────────────────────────────────────────────────────
step "Cleaning previous run"
rm -rf schemas drift_reports
ok "schemas/ and drift_reports/ cleared"

# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 1 — Infer schemas for three streams"
# ─────────────────────────────────────────────────────────────────────────────

step "Payments stream (300 events, with PII)"
streamforge init events/payments/stream_v1 --sample-size 300
divider

step "Flights stream (200 events)"
streamforge init events/flights/stream --sample-size 200
divider

step "Bookings stream (200 events, heavy PII)"
streamforge init events/bookings/stream --sample-size 200
divider

ok "Schemas written to schemas/"
echo ""
ls -1 schemas/

# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 2 — Inspect generated schemas"
# ─────────────────────────────────────────────────────────────────────────────

step "Payments schema (schema.yaml)"
cat schemas/stream_v1/schema.yaml
divider

step "Payments stream policy (stream_policy.yaml)"
cat schemas/stream_v1/stream_policy.yaml
divider

step "Payments inference report (summary)"
head -60 schemas/stream_v1/inference_report.md

# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 3 — Drift detection (plan)"
# ─────────────────────────────────────────────────────────────────────────────

step "Run 'plan' on the drifted payments stream (stream_v2)"
echo -e "${DIM}Expected: timestamp format changed, amount renamed, new PII field${RESET}\n"

# plan exits 1 on Tier 3 with default policy — capture it for demo purposes
streamforge plan events/payments/stream_v2_drift \
  --schema schemas/stream_v1/schema.yaml || true

divider

step "Drift report written:"
ls drift_reports/stream_v2_drift/ 2>/dev/null || echo "(none)"
echo ""
REPORT=$(ls drift_reports/stream_v2_drift/*.md 2>/dev/null | head -1)
if [ -n "$REPORT" ]; then
  cat "$REPORT"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 4 — Report view (all streams)"
# ─────────────────────────────────────────────────────────────────────────────

step "Payments"
streamforge report events/payments/stream_v1
divider

step "Flights"
streamforge report events/flights/stream
divider

step "Bookings"
streamforge report events/bookings/stream

# ─────────────────────────────────────────────────────────────────────────────
header "PHASE 5 — Watch mode (10s demo on clean payments)"
# ─────────────────────────────────────────────────────────────────────────────

echo -e "${DIM}Running watch for 12 seconds (2 cycles at 5s interval)...${RESET}"
echo -e "${DIM}Press Ctrl+C to stop early, or wait for auto-exit.${RESET}\n"

# Run watch in background, kill after 12s
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

echo -e "Schemas inferred:    ${GREEN}$(ls schemas/ | wc -l | tr -d ' ') streams${RESET}"
echo -e "Drift reports:       ${YELLOW}$(find drift_reports -name '*.md' 2>/dev/null | wc -l | tr -d ' ') report(s)${RESET}"
echo ""
echo -e "${DIM}To watch a stream continuously:${RESET}"
echo -e "  streamforge watch events/payments/stream_v1 --interval 30"
echo ""
echo -e "${DIM}To check drift as a CI gate (exits 1 on Tier 3):${RESET}"
echo -e "  streamforge plan events/payments/stream_v2_drift --schema schemas/stream_v1/schema.yaml"
echo ""
