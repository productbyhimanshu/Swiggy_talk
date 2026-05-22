"""Agent 2 — Intent validator (architecture §6).

Pure Pydantic + business logic. Zero LLM calls. Zero hallucination.
Checks business rules and returns either 'valid' or a clarification request.
"""

from __future__ import annotations

from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.responses import MessageBubble


class ValidationResult:
    """Result from Agent 2 validation."""

    __slots__ = ("valid", "clarify_field", "clarify_question", "quick_replies")

    def __init__(
        self,
        *,
        valid: bool,
        clarify_field: str | None = None,
        clarify_question: str | None = None,
        quick_replies: list[str] | None = None,
    ) -> None:
        self.valid = valid
        self.clarify_field = clarify_field
        self.clarify_question = clarify_question
        self.quick_replies = quick_replies

    def to_bubble(self) -> MessageBubble | None:
        """Return a MessageBubble for the clarification, or None if valid."""
        if self.valid or not self.clarify_question:
            return None
        return MessageBubble(
            text=self.clarify_question,
            quick_replies=self.quick_replies,
        )

    def __repr__(self) -> str:
        return (
            f"ValidationResult(valid={self.valid}, "
            f"clarify_field={self.clarify_field!r}, "
            f"clarify_question={self.clarify_question!r})"
        )


# ── ₹1,000 Swiggy Builders Club hard cap ──────────────────────────────────────
_SWIGGY_ORDER_CAP = 1_000


def validate_intent(intent: UserIntent) -> ValidationResult:
    """
    Validate parsed intent against Swiggy business rules.

    Priority order (first failure wins):
    1. Budget cap > ₹1000
    2. Veg/non-veg needs clarification
    3. No usable search signal

    Returns:
        ValidationResult with valid=True when everything is fine,
        or valid=False / clarify_question set when clarification is needed.
    """
    # ── Rule 1: Swiggy ₹1000 hard cap ─────────────────────────────────────────
    if intent.budget_max is not None and intent.budget_max > _SWIGGY_ORDER_CAP:
        return ValidationResult(
            valid=False,
            clarify_field="budget_max",
            clarify_question=(
                f"swiggy caps Builders Club orders at ₹{_SWIGGY_ORDER_CAP} — "
                "want to keep it under that?"
            ),
            quick_replies=["Under ₹500", "Under ₹800", f"Max ₹{_SWIGGY_ORDER_CAP}"],
        )

    # ── Rule 2: Veg / non-veg ambiguity ────────────────────────────────────────
    if intent.veg_nonveg == "NEEDS_CLARIFICATION":
        return ValidationResult(
            valid=True,  # valid=True: we have enough to search, but we need this
            clarify_field="veg_nonveg",
            clarify_question="veg or non-veg?",
            quick_replies=["🥦 Veg", "🍗 Non-veg", "Both work"],
        )

    # ── Rule 3: Must have at least one search signal ────────────────────────────
    signals = [
        intent.mood,
        intent.diet,
        intent.cuisine,
        intent.search_query,
    ]
    if not any(signals):
        return ValidationResult(
            valid=False,
            clarify_field="search_query",
            clarify_question="what are you in the mood for today? 🤔",
            quick_replies=["Biryani", "Pizza", "Healthy", "Surprise me"],
        )

    return ValidationResult(valid=True)
