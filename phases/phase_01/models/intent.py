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
