#!/usr/bin/env bash
# ============================================================================
# StreamForge — self-contained demo (no Kafka, no API key, fully deterministic)
# ============================================================================
# Every step is a REAL `streamforge` CLI command run against the event fixtures
# bundled in events/. Nothing is mocked. Safe to run on stage: deterministic.
#
#   bash demo/offline_demo.sh
#
# For the live-LLM variant (semantic types + enum detection), drop --offline and
# set GROQ_API_KEY — see demo/RUNBOOK.md.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$(mktemp -d)"
BOLD="\033[1m"; DIM="\033[2m"; CYAN="\033[36m"; RESET="\033[0m"

pause() { echo; read -rp "$(printf "${DIM}press ENTER to continue${RESET}")" _ || true; echo; }
act()   { echo; printf "${BOLD}${CYAN}── %s ──${RESET}\n" "$1"; echo; }

act "Act 1 — Infer a schema, deterministically (zero LLM calls)"
echo "  Same input + seed => same schema, every time. No API key needed."
python3 -m streamforge init events/payments/stream_v1 --offline -o "$OUT"
pause

act "Act 2 — Prove it works: a measurable scorecard"
echo "  Precision/recall/F1 vs hand-labeled ground truth, drift detection, and"
echo "  confidence calibration (ECE). This is the 'how do I know it works' answer."
python3 -m streamforge eval payments
pause

act "Act 3 — Inject drift → detect, explain, BLOCK"
echo "  Compare a drifted stream against the baseline. Each finding carries its"
echo "  statistical evidence; policy blocks the breaking change like a CI gate."
python3 -m streamforge plan events/payments/stream_v2_drift \
    --schema "$OUT/stream_v1/schema.yaml" || true

echo
echo "  Drift report (note the per-finding Evidence lines):"
report="$(ls -t drift_reports/stream_v2_drift/*.md 2>/dev/null | head -1 || true)"
[ -n "$report" ] && grep -E "^### |Evidence|Tier" "$report" | head -20

echo
printf "${BOLD}Done.${RESET} Schema written under %s\n" "$OUT"
