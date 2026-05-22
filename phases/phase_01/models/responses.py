"""Chat response models — formatting ships in Phase 6."""

from pydantic import BaseModel, Field


class MessageBubble(BaseModel):
    text: str
    quick_replies: list[str] | None = None


class ChatResponse(BaseModel):
    session_id: str
    bubbles: list[MessageBubble] = Field(default_factory=list)
