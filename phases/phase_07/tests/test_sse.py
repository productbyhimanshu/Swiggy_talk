"""Eval suite for Phase 7 SSE streaming."""

import pytest
import asyncio
import time
import json
from unittest.mock import patch, MagicMock, AsyncMock

from phases.phase_07.router import stream_response, ChatRequest
from phases.phase_07.session import get_session, clear_session
from phases.phase_01.models.state import ConversationState


class MockClientRequest:
    def __init__(self, disconnect=False):
        self.disconnect = disconnect
        
    async def is_disconnected(self):
        return self.disconnect


@pytest.fixture
def clean_session():
    clear_session("test_session")
    session = get_session("test_session")
    yield session
    clear_session("test_session")


@pytest.mark.asyncio
@patch("phases.phase_07.router.classify")
@patch("phases.phase_07.router.route_message")
async def test_sse_event_sequence(mock_route, mock_classify, clean_session):
    """7.E1 test_sse.py — event sequence order: bubbles → cards → [DONE]"""
    # Mocking
    from phases.phase_02.orchestrator import Route
    mock_classify.return_value = Route.NEW_SEARCH
    mock_route.return_value = [{"text": "Bubble 1"}, {"text": "Bubble 2"}]
    clean_session.has_recommendations = True
    clean_session.cached_results = [{"id": 1, "name": "Dish"}]
    
    req = ChatRequest(session_id="test_session", message="I want pizza")
    client_req = MockClientRequest()
    
    events = []
    async for event in stream_response(req, client_req):
        events.append(event.strip())
        
    assert len(events) == 4
    assert "Bubble 1" in events[0]
    assert "Bubble 2" in events[1]
    assert "cards" in events[2]
    assert "[DONE]" in events[3]


@pytest.mark.asyncio
@patch("phases.phase_07.router.classify")
@patch("phases.phase_07.router.route_message")
async def test_cart_action_emits_cart_update(mock_route, mock_classify, clean_session):
    """7.E2 test_sse.py — CART_ACTION emits cart_update"""
    from phases.phase_02.orchestrator import Route
    mock_classify.return_value = Route.CART_ACTION
    mock_route.return_value = [{"text": "Added!"}]
    
    req = ChatRequest(session_id="test_session", message="add it")
    client_req = MockClientRequest()
    
    events = []
    async for event in stream_response(req, client_req):
        events.append(event.strip())
        
    assert any("cart_update" in e for e in events)


@pytest.mark.asyncio
@patch("phases.phase_07.router.check_staleness")
async def test_staleness_first_event(mock_stale, clean_session):
    """7.E3 test_sse.py — staleness first event before pipeline"""
    mock_stale.return_value = True
    
    req = ChatRequest(session_id="test_session", message="hello")
    client_req = MockClientRequest()
    
    events = []
    async for event in stream_response(req, client_req):
        events.append(event.strip())
        
    assert "timed out" in events[0]
    assert "[DONE]" in events[1]


@pytest.mark.asyncio
@patch("phases.phase_07.router.classify")
@patch("phases.phase_07.router.route_message")
async def test_client_disconnect_mid_stream(mock_route, mock_classify, clean_session):
    """7.E4 test_sse.py — edge: client disconnect mid-stream — no session corruption"""
    from phases.phase_02.orchestrator import Route
    mock_classify.return_value = Route.NEW_SEARCH
    mock_route.return_value = [{"text": "1"}, {"text": "2"}, {"text": "3"}]
    
    req = ChatRequest(session_id="test_session", message="hello")
    
    class DisconnectingClient:
        def __init__(self):
            self.calls = 0
        async def is_disconnected(self):
            self.calls += 1
            return self.calls == 2 # Disconnects on second bubble
            
    client_req = DisconnectingClient()
    
    events = []
    async for event in stream_response(req, client_req):
        events.append(event.strip())
        
    # Should only emit first bubble and then stop, no [DONE]
    assert len(events) == 1
    assert "1" in events[0]
    # Ensure state was not corrupted
    assert clean_session.message_history[-1]["text"] == "hello"


@pytest.mark.asyncio
@patch("phases.phase_07.router.classify")
@patch("phases.phase_07.router.route_message")
async def test_cart_action_latency(mock_route, mock_classify, clean_session):
    """7.E5 test_sse.py — latency: cart_action path <200ms"""
    from phases.phase_02.orchestrator import Route
    mock_classify.return_value = Route.CART_ACTION
    
    # We mock route_message which is what typically contains LLM logic
    async def mock_instant(*args, **kwargs):
        return [{"text": "Done"}]
    mock_route.side_effect = mock_instant
    
    req = ChatRequest(session_id="test_session", message="add it")
    client_req = MockClientRequest()
    
    start = time.perf_counter()
    async for _ in stream_response(req, client_req):
        pass
    latency_ms = (time.perf_counter() - start) * 1000
    
    assert latency_ms < 200
