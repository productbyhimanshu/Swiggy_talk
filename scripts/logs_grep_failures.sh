#!/usr/bin/env bash
# Print recent warnings/errors from both log files
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
APP="$LOG_DIR/${LOG_FILE_NAME:-swiggy-talk.log}"
ERR="$LOG_DIR/${LOG_ERRORS_FILE_NAME:-errors.log}"

echo "=== $ERR (last 50 lines) ==="
if [[ -f "$ERR" ]]; then
  tail -50 "$ERR"
else
  echo "(missing)"
fi

echo ""
echo "=== $APP — level error (last 30) ==="
if [[ -f "$APP" ]]; then
  grep '"level": "error"' "$APP" 2>/dev/null | tail -30 || echo "(none)"
else
  echo "(missing)"
fi
