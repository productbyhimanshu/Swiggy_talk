"""Phase 4 — Swiggy read path: search, menu, filters, ETA parsing.

Architecture §6: Hard filter gates — Open → Rating → ETA → Diet → Budget.
No write tools here (cart ships in Phase 9). place_food_order stays blocked.
"""

PHASE = 4
STATUS = "done"

from phases.phase_04.services.swiggy_read import SwiggyReadClient, SwiggyUnavailableError
from phases.phase_04.utils.filters import apply_filters
from phases.phase_04.utils.parse_eta import parse_eta

__all__ = [
    "PHASE",
    "STATUS",
    "SwiggyReadClient",
    "SwiggyUnavailableError",
    "apply_filters",
    "parse_eta",
]
