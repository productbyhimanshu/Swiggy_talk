"""Conversation state — architecture §5."""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from phases.phase_00.config import get_settings


class ConversationState(BaseModel):
    session_id: str
    awaiting_clarification: bool = False
    clarify_field: str | None = None
    current_intent: dict | None = None
    has_recommendations: bool = False
    cached_results: list[dict] = Field(default_factory=list)
    current_restaurant_id: str | None = None
    cart_has_items: bool = False
    cart_restaurant_id: str | None = None
    scheduled_order: dict | None = None
    message_history: list[dict] = Field(default_factory=list)
    last_activity: datetime = Field(default_factory=datetime.now)
    address_id: str | None = None

    def get_context_window(self) -> list[dict]:
        return self.message_history[-6:]

    def append_message(self, role: str, text: str, **extra: object) -> None:
        entry = {"role": role, "text": text, **extra}
        self.message_history.append(entry)
        self.touch_activity()

    def touch_activity(self) -> None:
        self.last_activity = datetime.now()

    def to_public_dict(self) -> dict:
        """Safe subset for API responses."""
        return {
            "session_id": self.session_id,
            "awaiting_clarification": self.awaiting_clarification,
            "has_recommendations": self.has_recommendations,
            "cart_has_items": self.cart_has_items,
            "address_id": self.address_id,
            "message_count": len(self.message_history),
            "last_activity": self.last_activity.isoformat(),
        }


def check_staleness(
    state: ConversationState,
    timeout_minutes: int | None = None,
) -> bool:
    """
    If idle longer than timeout, invalidate cached search data.
    Returns True when stale (caches cleared).
    """
    if timeout_minutes is None:
        timeout_minutes = get_settings().session_timeout_minutes

    if datetime.now() - state.last_activity <= timedelta(minutes=timeout_minutes):
        return False

    state.cached_results = []
    state.has_recommendations = False
    state.current_restaurant_id = None
    return True
