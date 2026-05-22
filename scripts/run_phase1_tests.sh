#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT"
export ORDER_ENABLED=false
export EVAL_SUITE_PASSED=false
"$ROOT/backend/.venv/bin/pytest" "$ROOT/phases/phase_00/tests" "$ROOT/phases/phase_01/tests" -v "$@"
