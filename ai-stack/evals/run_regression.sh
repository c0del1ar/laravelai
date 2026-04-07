#!/usr/bin/env sh
set -eu

BASE_URL="${1:-http://127.0.0.1:8008}"
MIN_SCORE="${2:-0.66}"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python3 "$SCRIPT_DIR/run_eval.py" \
  --base-url "$BASE_URL" \
  --cases "$SCRIPT_DIR/eval_cases.jsonl" \
  --output "$SCRIPT_DIR/eval_report.json" \
  --min-score "$MIN_SCORE"
