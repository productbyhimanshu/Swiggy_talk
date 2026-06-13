"""User intent schema — full parsing ships in Phase 3."""

from pydantic import BaseModel, Field


class UserIntent(BaseModel):
    mood: str | None = None
    diet: str | None = None
    budget_max: int | None = Field(default=None, ge=1, le=5000)
    timing: str | None = None
    timing_type: str | None = None
    cuisine: str | None = None
    veg_nonveg: str | None = None
    speed: str | None = None
    search_query: str | None = None
    # Bhook's confidence that this intent is specific enough to act on without
    # asking more questions. 1.0 = "I know exactly what they want", 0.0 = "I
    # have no idea". The orchestrator uses this to drive the clarification
    # ladder: ≥0.8 search immediately, 0.5–0.8 ask one probe, <0.5 ask two.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # The single best follow-up question to ask, set when confidence < 0.8.
    # Free-text so the model can phrase it naturally ("for one or sharing?").
    clarify_probe: str | None = None
    # 2–3 quick-reply chips for the probe, so the user doesn't have to type.
    clarify_options: list[str] | None = None
