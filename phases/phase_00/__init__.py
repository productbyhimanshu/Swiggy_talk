"""Phase 0 — env, OAuth, Swiggy HTTP client, logging, order guard."""

PHASE = 0
STATUS = "done"

from phases.phase_00.config import Settings, get_settings
from phases.phase_00.main import app

__all__ = ["PHASE", "STATUS", "Settings", "get_settings", "app"]
