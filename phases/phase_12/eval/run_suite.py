"""Phase 12 eval — run_suite.py (enhanced with result reporting).

Runs all phase tests (0–11), prints a pass/fail matrix, and returns
the exit code. The user must set EVAL_SUITE_PASSED=true manually
in their .env after this passes — it is NOT set automatically.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASES_ROOT = ROOT / "phases"

# Ordered phase test directories (skip phase_12 to avoid circular)
PHASE_TEST_DIRS = [
    f"phases/phase_{str(i).zfill(2)}/tests"
    for i in range(0, 12)
    if (ROOT / f"phases/phase_{str(i).zfill(2)}/tests").exists()
]

MATRIX = [
    ("Intent (3.E*)",            "≥95%",               "phases/phase_03/tests"),
    ("Routing (2.E*)",           "100% regex",          "phases/phase_02/tests"),
    ("Filters (4.E*)",           "100%",                "phases/phase_04/tests"),
    ("Scoring (5.E*)",           "≥80% human agree",   "phases/phase_05/tests"),
    ("Timing (11.E*)",           "100%",                "phases/phase_11/tests"),
    ("Persona (6.E*)",           "0% fabrication",      "phases/phase_06/tests"),
    ("SSE (7.E*)",               "contract+latency",    "phases/phase_07/tests"),
    ("Session/Staleness (1.E*)", "state cleared",       "phases/phase_01/tests"),
    ("Cart rollback (9.E*)",     "pass",                "phases/phase_09/tests"),
    ("Retries/fallbacks (10.E*)","pass",                "phases/phase_10/tests"),
    ("Config/order guard (0.E*)","pass",                "phases/phase_00/tests"),
]


def run_suite(verbose: bool = False) -> int:
    """Run all phase test directories. Returns pytest exit code (0 = all pass)."""
    args = [sys.executable, "-m", "pytest"]
    args += PHASE_TEST_DIRS
    args += ["--tb=short", "-q"] if not verbose else ["--tb=short", "-v"]

    env_override = {
        "ORDER_ENABLED": "false",
        "EVAL_SUITE_PASSED": "false",
        "PYTHONPATH": str(ROOT),
    }

    import os
    env = {**os.environ, **env_override}

    print("\n" + "=" * 70)
    print("  SWIGGY TALK — PHASE 12 EVAL SUITE")
    print("=" * 70)
    print(f"  Running {len(PHASE_TEST_DIRS)} phase test directories...")
    print("=" * 70 + "\n")

    t0 = time.perf_counter()
    result = subprocess.run(args, cwd=ROOT, env=env, check=False)
    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 70)
    status = "✅ ALL PASS" if result.returncode == 0 else "❌ FAILURES DETECTED"
    print(f"  {status}  ({elapsed:.1f}s)")
    print("=" * 70)

    if result.returncode == 0:
        print("\n  ✅ EVAL GATE PASSED")
        print("  Next step: manually set EVAL_SUITE_PASSED=true in .env")
        print("  Then proceed to Phase 13 (real order placement).\n")
    else:
        print("\n  ❌ Fix failing tests before setting EVAL_SUITE_PASSED=true\n")

    return result.returncode


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    raise SystemExit(run_suite(verbose=verbose))
