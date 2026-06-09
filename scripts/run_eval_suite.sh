#!/usr/bin/env bash
# Phase 12 — full eval suite gate
# Usage: bash scripts/run_eval_suite.sh [-v]
#
# Runs all backend tests (phases 0–12) with ORDER_ENABLED=false.
# If all pass, prints the EVAL_SUITE_PASSED instruction.
# Human must set EVAL_SUITE_PASSED=true in .env manually — this script does NOT do it.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT"
export ORDER_ENABLED=false
export EVAL_SUITE_PASSED=false

PYTHON="$ROOT/backend/.venv/bin/python3"
if [[ ! -f "$PYTHON" ]]; then
  PYTHON="$(which python3.11 2>/dev/null || which python3)"
fi

echo ""
echo "======================================================================"
echo "  SWIGGY TALK — PHASE 12 EVAL SUITE GATE"
echo "======================================================================"
echo "  Python: $PYTHON"
echo "  Root:   $ROOT"
echo "======================================================================"
echo ""

"$PYTHON" -m pytest \
  "$ROOT/phases/phase_00/tests" \
  "$ROOT/phases/phase_01/tests" \
  "$ROOT/phases/phase_02/tests" \
  "$ROOT/phases/phase_03/tests" \
  "$ROOT/phases/phase_04/tests" \
  "$ROOT/phases/phase_05/tests" \
  "$ROOT/phases/phase_06/tests" \
  "$ROOT/phases/phase_07/tests" \
  "$ROOT/phases/phase_09/tests" \
  "$ROOT/phases/phase_10/tests" \
  "$ROOT/phases/phase_11/tests" \
  "$ROOT/phases/phase_12/tests" \
  --tb=short "${@}"

EXIT=$?

echo ""
echo "======================================================================"
if [[ $EXIT -eq 0 ]]; then
  echo "  ✅ EVAL SUITE PASSED"
  echo ""
  echo "  Next steps:"
  echo "  1. Add to your .env:  EVAL_SUITE_PASSED=true"
  echo "  2. Do NOT set ORDER_ENABLED=true until Phase 13 human sign-off"
  echo "  3. Proceed to Phase 13 → real order placement"
else
  echo "  ❌ EVAL SUITE FAILED — fix errors before Phase 13"
fi
echo "======================================================================"
echo ""

exit $EXIT
