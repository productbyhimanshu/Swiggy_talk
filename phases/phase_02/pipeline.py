"""Orchestrator pipeline — classify then dispatch stub handler."""

from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.state import ConversationState
from phases.phase_02.gemini_classify import gemini_classify
from phases.phase_02.handlers import HANDLERS
from phases.phase_02.orchestrator import Route, classify

log = get_logger(__name__)


async def classify_message(message: str, state: ConversationState) -> tuple[Route, bool]:
    """Full classify including Gemini when regex returns AMBIGUOUS. Returns (route, used_gemini)."""
    route = classify(message, state)
    if route != Route.AMBIGUOUS:
        log.info("route_classified", route=route.value, method="regex")
        return route, False

    route = await gemini_classify(message, state)
    log.info("route_classified", route=route.value, method="gemini")
    return route, True


async def run_pipeline(message: str, state: ConversationState) -> dict:
    """Classify message and run the stub handler for that route."""
    route, used_gemini = await classify_message(message, state)
    handler = HANDLERS.get(route)
    if handler is None:
        log.warning("pipeline_no_handler", route=route.value)
        route = Route.NEW_SEARCH
        handler = HANDLERS[Route.NEW_SEARCH]

    result = handler(message, state)
    state.append_message("user", message)
    log.info(
        "pipeline_complete",
        route=route.value,
        agents_called=result.get("agents", []),
        gemini_calls=1 if used_gemini else 0,
    )
    return result
