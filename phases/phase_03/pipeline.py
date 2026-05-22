"""Phase 3 pipeline — wires Agent 1 + Agent 2 into the NEW_SEARCH / CLARIFY_REPLY routes.

Called by the Phase 2 `run_pipeline` when route is NEW_SEARCH or CLARIFY_REPLY.
Returns a dict compatible with Phase 2 handler output format.
"""

from __future__ import annotations

from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.state import ConversationState
from phases.phase_03.agents.intent_parser import IntentParseError, parse_intent
from phases.phase_03.agents.validator import validate_intent

log = get_logger(__name__)

# ── Fallback bubble text when Agent 1 fails completely ────────────────────────
_INTENT_FAIL_TEXT = "sorry, didn't quite catch that — could you say it differently? 🤔"
_INTENT_FAIL_REPLIES = ["Try again", "Show popular dishes"]


def _bubble(text: str, quick_replies: list[str] | None = None) -> dict:
    b: dict = {"text": text}
    if quick_replies:
        b["quick_replies"] = quick_replies
    return b


async def run_intent_pipeline(
    message: str,
    state: ConversationState,
) -> dict:
    """
    Run Agent 1 → Agent 2 for NEW_SEARCH / CLARIFY_REPLY routes.

    Returns:
        Phase 2-compatible handler dict:
        {
            "route": str,
            "bubbles": list[dict],
            "agents": list[str],
            "intent": dict | None,            # populated on success
            "needs_clarification": bool,
            "clarify_field": str | None,
        }
    """
    context = state.get_context_window()[-2:]  # token budget: last 2 only

    # ── Agent 1: parse intent ──────────────────────────────────────────────────
    try:
        intent = await parse_intent(message, context)
    except IntentParseError as exc:
        log.warning("agent1_failed", error=str(exc), session=state.session_id)
        return {
            "route": "new_search",
            "bubbles": [_bubble(_INTENT_FAIL_TEXT, _INTENT_FAIL_REPLIES)],
            "agents": ["intent"],
            "intent": None,
            "needs_clarification": False,
            "clarify_field": None,
            "error": "intent_parse_failed",
        }

    log.info(
        "agent1_ok",
        session=state.session_id,
        search_query=intent.search_query,
        cuisine=intent.cuisine,
        budget_max=intent.budget_max,
        veg_nonveg=intent.veg_nonveg,
    )

    # ── Agent 2: validate ──────────────────────────────────────────────────────
    validation = validate_intent(intent)

    if not validation.valid:
        # Clarification needed — update state so next message is CLARIFY_REPLY
        state.awaiting_clarification = True
        state.clarify_field = validation.clarify_field

        clarify_bubble = validation.to_bubble()
        bubbles = [clarify_bubble.model_dump()] if clarify_bubble else []

        log.info(
            "agent2_clarify",
            session=state.session_id,
            field=validation.clarify_field,
        )

        return {
            "route": "new_search",
            "bubbles": bubbles,
            "agents": ["intent", "validate"],
            "intent": intent.model_dump(),
            "needs_clarification": True,
            "clarify_field": validation.clarify_field,
        }

    # Veg clarification requested (valid=True but clarify_field set)
    if validation.clarify_field == "veg_nonveg":
        state.awaiting_clarification = True
        state.clarify_field = "veg_nonveg"
        # Save intent so far — will be enriched on reply
        state.current_intent = intent.model_dump()

        clarify_bubble = validation.to_bubble()
        bubbles = [clarify_bubble.model_dump()] if clarify_bubble else []

        log.info(
            "agent2_veg_clarify",
            session=state.session_id,
        )

        return {
            "route": "new_search",
            "bubbles": bubbles,
            "agents": ["intent", "validate"],
            "intent": intent.model_dump(),
            "needs_clarification": True,
            "clarify_field": "veg_nonveg",
        }

    # ── All good — store intent; Phase 5 scorer takes over from here ───────────
    state.current_intent = intent.model_dump()
    state.awaiting_clarification = False
    state.clarify_field = None

    log.info(
        "agent2_ok",
        session=state.session_id,
        intent=intent.model_dump(),
    )

    return {
        "route": "new_search",
        "bubbles": [_bubble("on it — finding the best options for you... 🔍")],
        "agents": ["intent", "validate"],
        "intent": intent.model_dump(),
        "needs_clarification": False,
        "clarify_field": None,
    }
