"""Phase 3 — Agent 1 (intent parser) tests.

Mix of LOCAL (mocked Gemini) and fixture-based tests.
Covers exit gates 3.E1–3.E3 and 3.E7.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from phases.phase_01.models.intent import UserIntent
from phases.phase_03.agents import intent_parser as ip_mod
from phases.phase_03.agents.intent_parser import IntentParseError, parse_intent


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_intent(**kwargs) -> UserIntent:
    return UserIntent(**kwargs)


async def _ok_override(message: str, context: list[dict]) -> UserIntent:
    """Mock Agent 1 that always returns a sensible intent."""
    return UserIntent(search_query="biryani", budget_max=300, veg_nonveg="nonveg")


async def _fail_override(message: str, context: list[dict]) -> UserIntent:
    raise RuntimeError("Gemini 500")


def _cleanup():
    ip_mod.set_parse_override(None)


# ── 3.E1: basic intent extraction via mock ─────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_intent_returns_user_intent():
    ip_mod.set_parse_override(_ok_override)
    try:
        result = await parse_intent("I want biryani under 300", [])
        assert isinstance(result, UserIntent)
        assert result.search_query == "biryani"
        assert result.budget_max == 300
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_parse_intent_passes_context():
    received_context: list = []

    async def capturing_override(message: str, context: list[dict]) -> UserIntent:
        received_context.extend(context)
        return UserIntent(search_query="dal makhani")

    ip_mod.set_parse_override(capturing_override)
    try:
        ctx = [{"role": "user", "text": "hi"}, {"role": "ai", "text": "hey!"}]
        await parse_intent("I want something", ctx)
        assert received_context == ctx
    finally:
        _cleanup()


# ── 3.E2: invalid JSON / schema error from Gemini mock ────────────────────────

@pytest.mark.asyncio
async def test_parse_intent_raises_intent_parse_error_on_failure():
    ip_mod.set_parse_override(_fail_override)
    try:
        with pytest.raises(IntentParseError):
            await parse_intent("some message", [])
    finally:
        _cleanup()


# ── 3.E3: Pydantic rejects hallucinated fields ────────────────────────────────

def test_user_intent_rejects_negative_budget():
    with pytest.raises(ValidationError):
        UserIntent(budget_max=-500)


def test_user_intent_rejects_budget_above_5000():
    with pytest.raises(ValidationError):
        UserIntent(budget_max=5001)


def test_user_intent_accepts_budget_1():
    intent = UserIntent(budget_max=1)
    assert intent.budget_max == 1


def test_user_intent_accepts_budget_5000():
    intent = UserIntent(budget_max=5000)
    assert intent.budget_max == 5000


def test_user_intent_all_none_is_valid():
    """Empty intent is a valid Pydantic model (Agent 2 catches the signal-less case)."""
    intent = UserIntent()
    assert intent.search_query is None
    assert intent.budget_max is None


def test_user_intent_known_fields():
    intent = UserIntent(
        mood="comfort",
        diet="high_protein",
        budget_max=500,
        timing="13:00",
        timing_type="deliver_by",
        cuisine="north_indian",
        veg_nonveg="nonveg",
        speed="fast",
        search_query="dal",
    )
    assert intent.mood == "comfort"
    assert intent.timing == "13:00"


# ── 3.E7: Agent 1 failure → pipeline fallback ─────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_fallback_on_agent1_failure():
    """When Agent 1 fails, the pipeline must return a user-facing fallback."""
    from phases.phase_01.models.state import ConversationState
    from phases.phase_03.pipeline import run_intent_pipeline

    ip_mod.set_parse_override(_fail_override)
    try:
        state = ConversationState(session_id="test-fallback")
        result = await run_intent_pipeline("some message", state)
        assert result["error"] == "intent_parse_failed"
        assert result["intent"] is None
        assert len(result["bubbles"]) == 1
        assert result["bubbles"][0]["text"]  # non-empty fallback text
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_pipeline_sets_state_intent_on_success():
    ip_mod.set_parse_override(_ok_override)
    try:
        from phases.phase_01.models.state import ConversationState
        from phases.phase_03.pipeline import run_intent_pipeline

        state = ConversationState(session_id="test-state")
        result = await run_intent_pipeline("I want biryani under 300", state)
        assert result["intent"] is not None
        assert state.current_intent is not None
        assert state.current_intent["search_query"] == "biryani"
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_pipeline_clarifies_over_budget():
    async def over_budget_override(message: str, context: list[dict]) -> UserIntent:
        return UserIntent(search_query="biryani", budget_max=2000)

    ip_mod.set_parse_override(over_budget_override)
    try:
        from phases.phase_01.models.state import ConversationState
        from phases.phase_03.pipeline import run_intent_pipeline

        state = ConversationState(session_id="test-budget")
        result = await run_intent_pipeline("want biryani budget 2000", state)
        assert result["needs_clarification"] is True
        assert result["clarify_field"] == "budget_max"
        assert state.awaiting_clarification is True
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_pipeline_clarifies_veg_nonveg():
    async def veg_unclear_override(message: str, context: list[dict]) -> UserIntent:
        return UserIntent(search_query="biryani", veg_nonveg="NEEDS_CLARIFICATION")

    ip_mod.set_parse_override(veg_unclear_override)
    try:
        from phases.phase_01.models.state import ConversationState
        from phases.phase_03.pipeline import run_intent_pipeline

        state = ConversationState(session_id="test-veg")
        result = await run_intent_pipeline("I want some biryani", state)
        assert result["needs_clarification"] is True
        assert result["clarify_field"] == "veg_nonveg"
        assert state.clarify_field == "veg_nonveg"
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_pipeline_no_signals_clarifies():
    async def no_signal_override(message: str, context: list[dict]) -> UserIntent:
        return UserIntent()  # all None

    ip_mod.set_parse_override(no_signal_override)
    try:
        from phases.phase_01.models.state import ConversationState
        from phases.phase_03.pipeline import run_intent_pipeline

        state = ConversationState(session_id="test-nosignal")
        result = await run_intent_pipeline("hmm", state)
        assert result["needs_clarification"] is True
        assert result["clarify_field"] == "search_query"
    finally:
        _cleanup()
