"""Fast Gemini route label for ambiguous messages only."""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Awaitable

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.state import ConversationState
from phases.phase_02.orchestrator import Route

log = get_logger(__name__)

VALID_ROUTES = {r.value for r in Route if r != Route.AMBIGUOUS}

# Injectable for tests: async (message, state) -> Route
_classify_override: Callable[[str, ConversationState], Awaitable[Route]] | None = None


def set_classify_override(
    fn: Callable[[str, ConversationState], Awaitable[Route]] | None,
) -> None:
    global _classify_override
    _classify_override = fn


async def gemini_classify(message: str, state: ConversationState) -> Route:
    """Return route from Gemini JSON, or NEW_SEARCH on failure / missing API key."""
    if _classify_override is not None:
        try:
            return await asyncio.wait_for(
                _classify_override(message, state),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            log.warning("gemini_classify_failed", error="timeout")
            return Route.NEW_SEARCH
        except Exception as exc:
            log.warning("gemini_classify_failed", error=str(exc))
            return Route.NEW_SEARCH

    settings = get_settings()
    if not settings.gemini_api_key:
        log.warning("gemini_classify_skipped", reason="no_api_key")
        return Route.NEW_SEARCH

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call_gemini_sync, message, state),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        log.warning("gemini_classify_failed", error="timeout")
        return Route.NEW_SEARCH
    except Exception as exc:
        log.warning("gemini_classify_failed", error=str(exc))
        return Route.NEW_SEARCH


def _call_gemini_sync(message: str, state: ConversationState) -> Route:
    import google.generativeai as genai

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    context = state.get_context_window()[-2:]
    prompt = (
        "Classify the user message into exactly one route for a food ordering assistant.\n"
        f"Message: {message}\n"
        f"Recent context: {json.dumps(context)}\n"
        f'Return JSON only: {{"route": "<one of: {", ".join(sorted(VALID_ROUTES))}>"}}'
    )

    response = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0,
            "max_output_tokens": 20,
        },
    )

    raw = response.text or "{}"
    data = json.loads(raw)
    route_name = data.get("route", Route.NEW_SEARCH.value)
    if route_name not in VALID_ROUTES:
        return Route.NEW_SEARCH
    return Route(route_name)
