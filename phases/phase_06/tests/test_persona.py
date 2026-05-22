"""Eval suite for Phase 6 Agent 4 (Persona Formatter)."""

import pytest
import json
from phases.phase_01.models.intent import UserIntent
from phases.phase_06.agents.persona import format_recommendations


class MockGeminiClient:
    def __init__(self, mock_response=None, fail=False):
        self.mock_response = mock_response
        self.fail = fail
        self.calls = 0

    async def generate_content_async(self, contents, generation_config=None):
        self.calls += 1
        if self.fail:
            raise Exception("Gemini API Error")
            
        class MockResponse:
            def __init__(self, text):
                self.text = text
                
        return MockResponse(json.dumps(self.mock_response))


@pytest.fixture
def sample_top_6():
    return [
        {
            "name": "Spicy Paneer Tikka",
            "restaurant": "Punjabi Dhaba",
            "price": 250,
            "deliveryTime": "30 mins",
            "rating": 4.5
        },
        {
            "name": "Chicken Biryani",
            "restaurant": "Biryani Blues",
            "costForTwo": 400,
            "deliveryTime": "45 mins",
            "rating": 4.2
        }
    ]


@pytest.mark.asyncio
async def test_persona_no_fabrication(sample_top_6):
    """6.E1 test_persona.py — no price/name/ETA fabrication vs input."""
    intent = UserIntent()
    
    # Mock LLM returning exactly the data
    mock_bubbles = [
        {"text": "Hey! Found some great stuff.", "quick_replies": []},
        {"text": "Spicy Paneer Tikka from Punjabi Dhaba for ₹250 (30 mins, ★4.5).", "quick_replies": ["Add Tikka"]},
        {"text": "Chicken Biryani from Biryani Blues for ₹400 (45 mins, ★4.2).", "quick_replies": ["Add Biryani"]}
    ]
    
    client = MockGeminiClient(mock_response=mock_bubbles)
    bubbles = await format_recommendations(intent, sample_top_6, [], client)
    
    assert len(bubbles) == 3
    # Verify the exact fields made it in without hallucination
    assert "Spicy Paneer Tikka" in bubbles[1]["text"]
    assert "250" in bubbles[1]["text"]
    assert "30 mins" in bubbles[1]["text"]


@pytest.mark.asyncio
async def test_persona_line_limits(sample_top_6):
    """6.E2 test_persona.py — ≤2 lines per bubble."""
    intent = UserIntent()
    
    mock_bubbles = [
        {
            "text": "Line 1\nLine 2",
            "quick_replies": []
        }
    ]
    
    client = MockGeminiClient(mock_response=mock_bubbles)
    bubbles = await format_recommendations(intent, sample_top_6, [], client)
    
    for b in bubbles:
        lines = b["text"].split("\n")
        assert len(lines) <= 2, f"Bubble exceeded 2 lines: {b['text']}"


@pytest.mark.asyncio
async def test_persona_failure_fallback(sample_top_6):
    """6.E3 test_persona.py — failure: Agent 4 fails → plain format, data intact."""
    intent = UserIntent()
    client = MockGeminiClient(fail=True)
    
    bubbles = await format_recommendations(intent, sample_top_6, [], client)
    
    # Fallback generates 1 intro bubble, 2 item bubbles, 1 outro bubble
    assert len(bubbles) == 4
    
    # Check if raw data was safely piped
    assert "Spicy Paneer Tikka" in bubbles[1]["text"]
    assert "Punjabi Dhaba" in bubbles[1]["text"]
    assert "250" in bubbles[1]["text"]
    
    assert "Chicken Biryani" in bubbles[2]["text"]
    assert "Biryani Blues" in bubbles[2]["text"]
    assert "400" in bubbles[2]["text"]
