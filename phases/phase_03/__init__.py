"""Phase 3 — Agent 1 (intent parser) + Agent 2 (validator).

Architecture §6: Gemini 2.0 Flash structured output → Pydantic validation.
"""

PHASE = 3
STATUS = "done"

from phases.phase_03.agents.intent_parser import IntentParseError, parse_intent
from phases.phase_03.agents.validator import ValidationResult, validate_intent
from phases.phase_03.pipeline import run_intent_pipeline

__all__ = [
    "PHASE",
    "STATUS",
    "parse_intent",
    "IntentParseError",
    "validate_intent",
    "ValidationResult",
    "run_intent_pipeline",
]
