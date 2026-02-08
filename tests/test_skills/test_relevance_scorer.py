"""Tests for RelevanceScorer skill."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMResponseError
from paper_search.models import IntentType, ParsedIntent, PaperTag, RawPaper, ScoredPaper
from paper_search.skills.relevance_scorer import RelevanceScorer


class MockScorerLLM(LLMProvider):
    def __init__(self, response: dict | Exception | None = None) -> None:
        self._response = response
        self.call_count = 0

    async def complete(self, system_prompt: str, user_message: str) -> str:
        return ""

    async def complete_json(
        self, system_prompt: str, user_message: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.call_count += 1
        if isinstance(self._response, Exception):
            raise self._response
        if isinstance(self._response, dict):
            return self._response
        raise LLMResponseError("No response")


class DelayedScorerLLM(LLMProvider):
    def __init__(self, delay_s: float = 0.05) -> None:
        self.delay_s = delay_s
        self.call_count = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, system_prompt: str, user_message: str) -> str:
        return ""

    async def complete_json(
        self, system_prompt: str, user_message: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.call_count += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay_s)
            return {"results": []}
        finally:
            self.in_flight -= 1


_INTENT = ParsedIntent(
    topic="LLM in medical imaging",
    concepts=["LLM", "medical imaging"],
    intent_type=IntentType.SURVEY,
)


def _paper(title: str, id: str = "") -> RawPaper:
    return RawPaper(id=id or title.lower().replace(" ", "-"), title=title, source="test")


class TestRelevanceScorerBasic:
    @pytest.mark.asyncio
    async def test_score_basic(self):
        papers = [_paper("Paper A", "a"), _paper("Paper B", "b")]
        llm_response = {
            "results": [
                {"paper_id": "a", "relevance_score": 0.8, "relevance_reason": "Relevant", "tags": ["method"]},
                {"paper_id": "b", "relevance_score": 0.3, "relevance_reason": "Tangential", "tags": ["review"]},
            ]
        }
        llm = MockScorerLLM(llm_response)
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert len(result) == 2
        assert result[0].relevance_score == 0.8
        assert result[0].tags == [PaperTag.METHOD]
        assert result[1].relevance_score == 0.3

    @pytest.mark.asyncio
    async def test_batching(self):
        papers = [_paper(f"Paper {i}", str(i)) for i in range(25)]
        # Return minimal valid response for each paper
        def make_response():
            # This will be the same for all batches
            return {"results": []}

        llm = MockScorerLLM({"results": []})
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert llm.call_count == 3  # ceil(25/10) = 3
        assert len(result) == 25  # All get defaults since LLM returns empty results

    @pytest.mark.asyncio
    async def test_batching_with_concurrency(self):
        papers = [_paper(f"Paper {i}", str(i)) for i in range(40)]
        llm = DelayedScorerLLM(delay_s=0.03)
        scorer = RelevanceScorer(llm, batch_size=5, max_concurrency=4)
        result = await scorer.score(papers, _INTENT)

        assert len(result) == 40
        assert llm.call_count == 8  # ceil(40/5) = 8
        assert llm.max_in_flight >= 2

    @pytest.mark.asyncio
    async def test_score_clamping(self):
        papers = [_paper("Paper A", "a")]
        llm_response = {
            "results": [
                {"paper_id": "a", "relevance_score": 1.5, "relevance_reason": "Very", "tags": []},
            ]
        }
        llm = MockScorerLLM(llm_response)
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert result[0].relevance_score == 1.0

    @pytest.mark.asyncio
    async def test_score_clamping_negative(self):
        papers = [_paper("Paper A", "a")]
        llm_response = {
            "results": [
                {"paper_id": "a", "relevance_score": -0.3, "relevance_reason": "Nope", "tags": []},
            ]
        }
        llm = MockScorerLLM(llm_response)
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert result[0].relevance_score == 0.0

    @pytest.mark.asyncio
    async def test_missing_paper_default(self):
        papers = [_paper("Paper A", "a"), _paper("Paper B", "b")]
        # LLM only returns score for paper "a"
        llm_response = {
            "results": [
                {"paper_id": "a", "relevance_score": 0.9, "relevance_reason": "Great", "tags": []},
            ]
        }
        llm = MockScorerLLM(llm_response)
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert len(result) == 2
        assert result[0].relevance_score == 0.9
        assert result[1].relevance_score == 0.0
        assert result[1].relevance_reason == "Scoring unavailable"

    @pytest.mark.asyncio
    async def test_invalid_tag_filtering(self):
        papers = [_paper("Paper A", "a")]
        llm_response = {
            "results": [
                {"paper_id": "a", "relevance_score": 0.5, "relevance_reason": "Ok",
                 "tags": ["method", "invalid_tag", "review"]},
            ]
        }
        llm = MockScorerLLM(llm_response)
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert result[0].tags == [PaperTag.METHOD, PaperTag.REVIEW]

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        papers = [_paper("Paper A", "a"), _paper("Paper B", "b")]
        llm = MockScorerLLM(LLMError("API down"))
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score(papers, _INTENT)

        assert len(result) == 2
        for sp in result:
            assert sp.relevance_score == 0.0
            assert sp.relevance_reason == "Scoring unavailable"

    @pytest.mark.asyncio
    async def test_empty_input(self):
        llm = MockScorerLLM()
        scorer = RelevanceScorer(llm, batch_size=10)
        result = await scorer.score([], _INTENT)

        assert result == []
        assert llm.call_count == 0

    def test_truncation(self):
        long_title = "A" * 500
        long_snippet = "B" * 2000
        paper = RawPaper(id="x", title=long_title, snippet=long_snippet, source="test")

        scorer = RelevanceScorer(MockScorerLLM(), batch_size=10)
        msg = scorer._format_batch([paper], _INTENT)

        # Title should be truncated to 200
        assert "A" * 201 not in msg
        # Snippet should be truncated to 500
        assert "B" * 501 not in msg
