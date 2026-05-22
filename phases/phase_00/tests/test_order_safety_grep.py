"""Phase 0.E4 — ensure place_food_order is only reachable via guarded path."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PHASES_ROOT = REPO_ROOT / "phases"

ALLOWED_SUFFIXES = (
    "phase_00/services/swiggy_api.py",
    "phase_00/services/order_guard.py",
    "phase_13/routes/place_order.py",
)


def _is_allowed(path: Path) -> bool:
    rel = str(path.relative_to(PHASES_ROOT))
    if rel in ALLOWED_SUFFIXES:
        return True
    if path.name in ("test_order_guard.py", "test_order_safety_grep.py"):
        return True
    return False


def test_place_food_order_not_called_from_wrong_modules():
    violations: list[str] = []

    for path in PHASES_ROOT.rglob("*.py"):
        if _is_allowed(path):
            continue
        if "tests" in path.parts and path.name.startswith("test_"):
            continue
        if path.name == "__init__.py":
            continue
        text = path.read_text()
        if "place_food_order" in text:
            violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == [], (
        "place_food_order must only appear in guarded modules: "
        + ", ".join(violations)
    )
