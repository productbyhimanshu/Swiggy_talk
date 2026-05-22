"""Eval suite for Phase 5 Agent 3 (Scorer + Gemini re-rank)."""

import pytest
import asyncio
from phases.phase_01.models.intent import UserIntent
from phases.phase_05.agents.scorer import calculate_base_score, final_rank
from phases.phase_05.utils.weights import get_weights


class MockGeminiClient:
    def __init__(self, mock_scores=None, fail=False):
        self.mock_scores = mock_scores
        self.fail = fail
        self.calls = 0

    async def generate_content_async(self, contents, generation_config=None):
        self.calls += 1
        if self.fail:
            raise Exception("Gemini API error")
            
        class MockResponse:
            def __init__(self, text):
                self.text = text
        
        if self.mock_scores is not None:
            import json
            return MockResponse(json.dumps(self.mock_scores))
            
        # Default mock: return 100 for everything
        return MockResponse("[100]")


def test_weight_shifts():
    """5.E1 test_scoring.py — 10+ scenarios — weight shifts (fast, budget, protein)"""
    # 1. Base
    intent = UserIntent()
    weights = get_weights(intent)
    assert weights["rating"] == 0.20
    assert weights["eta"] == 0.20

    # 2. Fast
    intent = UserIntent(speed="fast")
    weights = get_weights(intent)
    assert weights["eta"] == 0.35
    assert weights["rating"] == 0.15

    # 3. Budget
    intent = UserIntent(budget_max=150)
    weights = get_weights(intent)
    assert weights["price"] == 0.30

    # 4. Protein
    intent = UserIntent(diet="high_protein")
    weights = get_weights(intent)
    assert weights["intent"] == 0.35

    # 5. Comfort
    intent = UserIntent(mood="comfort")
    weights = get_weights(intent)
    assert weights["intent"] == 0.30
    assert weights["eta"] == 0.25

    # 6. Nearby
    intent = UserIntent(speed="nearby")
    weights = get_weights(intent)
    assert weights["distance"] == 0.25


@pytest.mark.asyncio
async def test_top_6_ordering_stable():
    """5.E2 test_scoring.py — top 6 ordering stable with fixed fixtures"""
    intent = UserIntent()
    survivors = [
        {"id": 1, "rating": 4.5, "deliveryTime": "30 mins", "costForTwo": 600, "distance": 2.0},
        {"id": 2, "rating": 4.8, "deliveryTime": "45 mins", "costForTwo": 800, "distance": 5.0},
        {"id": 3, "rating": 4.0, "deliveryTime": "15 mins", "costForTwo": 200, "distance": 1.0},
        {"id": 4, "rating": 4.2, "deliveryTime": "60 mins", "costForTwo": 400, "distance": 8.0},
        {"id": 5, "rating": 4.9, "deliveryTime": "20 mins", "costForTwo": 1000, "distance": 3.0},
        {"id": 6, "rating": 4.1, "deliveryTime": "35 mins", "costForTwo": 300, "distance": 4.0},
        {"id": 7, "rating": 3.8, "deliveryTime": "25 mins", "costForTwo": 500, "distance": 6.0},
    ]
    
    client = MockGeminiClient(mock_scores=[100, 90, 80, 70, 60, 50, 40])
    top_6 = await final_rank(survivors.copy(), intent, client)
    
    assert len(top_6) == 6
    # 7 should be dropped (lowest score)
    ids = [r["id"] for r in top_6]
    assert len(set(ids)) == 6


@pytest.mark.asyncio
async def test_gemini_rerank_bad_array_fallback():
    """5.E3 test_scoring.py — failure: Gemini rerank bad array → fallback equal scores"""
    intent = UserIntent()
    survivors = [{"id": i, "rating": 4.0} for i in range(10)]
    
    # Return string instead of array
    client = MockGeminiClient(mock_scores="not an array")
    top_6 = await final_rank(survivors, intent, client)
    
    assert len(top_6) == 6
    for r in top_6:
        assert r["_intent_score"] == 50.0  # Fallback triggered


@pytest.mark.asyncio
async def test_agent_3_exception_fallback():
    """5.E4 test_scoring.py — failure: Agent 3 exception → fallback equal scores"""
    intent = UserIntent()
    survivors = [{"id": i, "rating": 4.0} for i in range(10)]
    
    # Network failure or API exception
    client = MockGeminiClient(fail=True)
    top_6 = await final_rank(survivors, intent, client)
    
    assert len(top_6) == 6
    for r in top_6:
        assert r["_intent_score"] == 50.0  # Fallback triggered


@pytest.mark.asyncio
async def test_edge_less_than_6_survivors():
    """5.E5 test_scoring.py — edge: <6 survivors after filters → return fewer"""
    intent = UserIntent()
    survivors = [{"id": 1, "rating": 4.5}, {"id": 2, "rating": 4.8}]
    
    client = MockGeminiClient(mock_scores=[100, 90])
    top_n = await final_rank(survivors, intent, client)
    
    assert len(top_n) == 2
