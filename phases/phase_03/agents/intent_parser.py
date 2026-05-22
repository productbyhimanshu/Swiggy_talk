"""Agent 1 — Intent parser (architecture §6).

Calls Gemini 2.0 Flash with a JSON response schema matching UserIntent.
Retries 3× on transient errors before raising IntentParseError.
Context sent: current message + last 2 messages only (token budget).
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Awaitable

from pydantic import ValidationError

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.intent import UserIntent

log = get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_SECS = 1.0


class IntentParseError(Exception):
    """Raised after all retries are exhausted on Agent 1 failure."""


# ── Injectable override for tests ─────────────────────────────────────────────
# Signature: async (message: str, context: list[dict]) -> UserIntent
_parse_override: Callable[[str, list[dict]], Awaitable[UserIntent]] | None = None


def set_parse_override(
    fn: Callable[[str, list[dict]], Awaitable[UserIntent]] | None,
) -> None:
    global _parse_override
    _parse_override = fn


# ── Public API ─────────────────────────────────────────────────────────────────

async def parse_intent(message: str, context: list[dict]) -> UserIntent:
    """
    Extract structured UserIntent from a user message.

    Args:
        message: The raw user message.
        context: Last 2 conversation turns (not full history — token budget).

    Returns:
        Validated UserIntent instance.

    Raises:
        IntentParseError: After 3 failed Gemini attempts.
    """
    if _parse_override is not None:
        try:
            return await _parse_override(message, context)
        except Exception as exc:
            raise IntentParseError(f"override raised: {exc}") from exc

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            intent = await asyncio.to_thread(_call_gemini_sync, message, context)
            log.info(
                "intent_parsed",
                attempt=attempt,
                search_query=intent.search_query,
                cuisine=intent.cuisine,
                budget_max=intent.budget_max,
            )
            return intent
        except (IntentParseError, ValidationError) as exc:
            # Don't retry schema/validation errors — they won't improve
            log.warning("intent_parse_schema_error", error=str(exc), attempt=attempt)
            raise IntentParseError(str(exc)) from exc
        except Exception as exc:
            last_error = exc
            log.warning(
                "intent_parse_retry",
                attempt=attempt,
                max=_MAX_RETRIES,
                error=str(exc),
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_SECS * attempt)

    raise IntentParseError(
        f"Agent 1 failed after {_MAX_RETRIES} attempts: {last_error}"
    ) from last_error


# ── Gemini sync call (run in thread) ──────────────────────────────────────────

def _call_gemini_sync(message: str, context: list[dict]) -> UserIntent:
    """Synchronous Gemini call — executed in a thread via asyncio.to_thread."""
    import google.generativeai as genai  # local import keeps startup fast

    settings = get_settings()
    if not settings.gemini_api_key:
        raise IntentParseError("GEMINI_API_KEY not set — cannot call Agent 1")

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash-lite")

    raw_schema = UserIntent.model_json_schema()
    
    def strip_unsupported(schema_dict: dict) -> dict:
        """Keep ONLY keys supported by Gemini 2.0 API response_schema."""
        if not isinstance(schema_dict, dict):
            return schema_dict
            
        cleaned = {}
        allowed_keys = {"type", "properties", "required", "items", "description", "enum"}
        
        # Handle anyOf by taking the first non-null type
        if "anyOf" in schema_dict:
            types = schema_dict["anyOf"]
            for t in types:
                if t.get("type") != "null":
                    cleaned.update(strip_unsupported(t))
                    break
        
        for k, v in schema_dict.items():
            if k not in allowed_keys:
                continue
                
            if isinstance(v, dict):
                cleaned[k] = strip_unsupported(v)
            elif isinstance(v, list):
                if k == "required":
                    cleaned[k] = v
                else:
                    cleaned[k] = [strip_unsupported(i) if isinstance(i, dict) else i for i in v]
            else:
                cleaned[k] = v
                
        return cleaned

    schema = strip_unsupported(raw_schema)

    # Token budget: current message + last 2 context turns only
    context_trimmed = context[-2:] if context else []
    prompt = _build_prompt(message, context_trimmed)

    response = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.1,
            "max_output_tokens": 256,
        },
    )

    raw = response.text or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntentParseError(f"Gemini returned non-JSON: {raw[:200]}") from exc

    # Pydantic validates — rejects hallucinated fields (e.g. budget_max: -500)
    try:
        return UserIntent.model_validate(data)
    except ValidationError as exc:
        raise IntentParseError(f"UserIntent validation failed: {exc}") from exc


def _build_prompt(message: str, context: list[dict]) -> str:
    ctx_text = ""
    if context:
        ctx_lines = [f"  [{t.get('role','?')}]: {t.get('text','')}" for t in context]
        ctx_text = "\nRecent conversation:\n" + "\n".join(ctx_lines)

    return (
        "You are the intent parser for a food ordering assistant.\n"
        "Extract structured intent from the user's message.\n"
        "Rules:\n"
        "- budget_max must be between 1–5000 INR if present; null otherwise.\n"
        "- timing must be HH:MM 24h format or null.\n"
        "- veg_nonveg: 'veg', 'nonveg', 'both', 'NEEDS_CLARIFICATION', or null.\n"
        "- speed: 'fast', 'normal', or null.\n"
        "- Set search_query to the best Swiggy keyword for this request.\n"
        "- If the user is refining a previous request (context shows prior intent), "
        "update only the changed fields; carry forward the rest.\n"
        f"{ctx_text}\n"
        f"User message: {message}\n"
        "Return ONLY valid JSON matching the schema."
    )
