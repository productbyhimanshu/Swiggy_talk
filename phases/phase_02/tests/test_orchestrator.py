"""Phase 2 — routing tests (regex, guards, Gemini mock, fallbacks)."""

import asyncio

import pytest

from phases.phase_01.models.state import ConversationState
from phases.phase_02 import gemini_classify as gc_mod
from phases.phase_02.orchestrator import Route, classify, classify_regex
from phases.phase_02.pipeline import classify_message, run_pipeline


def _state(**kwargs) -> ConversationState:
    base = {"session_id": "test-session"}
    base.update(kwargs)
    return ConversationState(**base)


# --- 2.E1: 15+ regex cases ---

@pytest.mark.parametrize(
    "message,expected",
    [
        ("hi", Route.GREETING),
        ("Hey!", Route.GREETING),
        ("thanks", Route.GREETING),
        ("cancel that", Route.CANCEL),
        ("nevermind", Route.CANCEL),
        ("clear cart", Route.CANCEL),
        ("add paneer to cart", Route.CART_ACTION),
        ("remove the biryani", Route.CART_ACTION),
        ("increase quantity", Route.CART_ACTION),
        ("lunch at 1 PM", Route.SCHEDULE),
        ("deliver by 8", Route.SCHEDULE),
        ("biryani", Route.NEW_SEARCH),
        ("ok", Route.GREETING),
    ],
)
def test_regex_routes(message, expected):
    assert classify(message, _state()) == expected


@pytest.mark.parametrize(
    "message,state_kwargs,expected",
    [
        ("place order", {}, Route.NEW_SEARCH),  # guard: empty cart
        ("place order", {"cart_has_items": True}, Route.ORDER),
        ("checkout now", {"cart_has_items": True}, Route.ORDER),
        ("make it cheaper", {}, Route.NEW_SEARCH),  # guard: no recommendations
        ("re-suggest", {"has_recommendations": True}, Route.REFINE),
        ("faster options", {"has_recommendations": True}, Route.REFINE),
        ("what else", {}, Route.NEW_SEARCH),  # guard: no restaurant
        (
            "same restaurant",
            {"current_restaurant_id": "r1"},
            Route.IN_RESTAURANT,
        ),
        ("search dal in same place", {"current_restaurant_id": "r1"}, Route.IN_RESTAURANT),
    ],
)
def test_regex_with_context_guards(message, state_kwargs, expected):
    assert classify(message, _state(**state_kwargs)) == expected


# --- 2.E2: clarification priority ---

def test_awaiting_clarification_forces_clarify_reply():
    state = _state(awaiting_clarification=True)
    assert classify("anything here", state) == Route.CLARIFY_REPLY
    assert classify("cancel", state) == Route.CLARIFY_REPLY  # clarify beats regex


# --- 2.E3: ambiguous + mocked Gemini ---

@pytest.mark.asyncio
async def test_ambiguous_uses_gemini_mock():
    gc_mod.set_classify_override(None)

    async def mock_gemini(msg: str, state: ConversationState) -> Route:
        return Route.REFINE

    gc_mod.set_classify_override(mock_gemini)
    state = _state(has_recommendations=True)
    route, used = await classify_message(
        "I'm not sure what I want but maybe something lighter and healthy please",
        state,
    )
    assert route == Route.REFINE
    assert used is True
    gc_mod.set_classify_override(None)


@pytest.mark.asyncio
async def test_ambiguous_gemini_returns_valid_enum():
    async def mock_gemini(msg: str, state: ConversationState) -> Route:
        return Route.CART_ACTION

    gc_mod.set_classify_override(mock_gemini)
    route, _ = await classify_message("put that in my cart", _state())
    assert route == Route.CART_ACTION
    gc_mod.set_classify_override(None)


# --- 2.E4: edge cases ---

def test_empty_message_new_search():
    assert classify("", _state()) == Route.NEW_SEARCH
    assert classify("   ", _state()) == Route.NEW_SEARCH


def test_short_message_new_search():
    assert classify("biry", _state()) == Route.NEW_SEARCH


def test_long_unmatched_ambiguous():
    assert (
        classify("I want something tasty but unsure what to pick", _state())
        == Route.AMBIGUOUS
    )


def test_emoji_only_short_is_new_search():
    assert classify("😋", _state()) == Route.NEW_SEARCH


def test_mixed_language_long_ambiguous():
    assert classify("mujhe kuch accha khana hai please suggest", _state()) == Route.AMBIGUOUS


# --- 2.E5: Gemini failure → NEW_SEARCH ---

@pytest.mark.asyncio
async def test_gemini_timeout_fallback_new_search():
    async def slow(_msg: str, _state: ConversationState) -> Route:
        await asyncio.sleep(10)
        return Route.GREETING

    gc_mod.set_classify_override(slow)
    route, used = await classify_message(
        "something completely unclear here and I cannot decide at all today",
        _state(),
    )
    assert route == Route.NEW_SEARCH
    assert used is True
    gc_mod.set_classify_override(None)


@pytest.mark.asyncio
async def test_gemini_exception_fallback():
    async def boom(_msg: str, _state: ConversationState) -> Route:
        raise RuntimeError("api down")

    gc_mod.set_classify_override(boom)
    route, _ = await classify_message(
        "feeling adventurous for dinner tonight and open to anything you suggest",
        _state(),
    )
    assert route == Route.NEW_SEARCH
    gc_mod.set_classify_override(None)


# --- pipeline stubs ---

@pytest.mark.asyncio
async def test_run_pipeline_greeting():
    from phases.phase_01.services.session import clear_all_sessions, get_session

    clear_all_sessions()
    state = get_session("pipe-1")
    result = await run_pipeline("hello", state)
    assert result["route"] == Route.GREETING.value
    assert result["bubbles"]
    assert len(state.message_history) == 1


@pytest.mark.asyncio
async def test_run_pipeline_order_stub():
    state = _state(cart_has_items=True)
    result = await run_pipeline("place order", state)
    assert result["route"] == Route.ORDER.value
    assert result.get("requires_user_confirm") is True
