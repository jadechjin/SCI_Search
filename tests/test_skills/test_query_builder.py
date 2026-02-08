"""Tests for QueryBuilder skill."""

from __future__ import annotations

import json
from typing import Any

import pytest

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMResponseError
from paper_search.models import (
    IntentType,
    ParsedIntent,
    QueryBuilderInput,
    SearchConstraints,
)
from paper_search.prompts.query_building import QUERY_BUILDING_SYSTEM
from paper_search.skills.query_builder import QueryBuilder


class MockLLM(LLMProvider):
    def __init__(self, response: dict | Exception | None = None) -> None:
        self._response = response
        self.last_user_msg: str = ""

    def _error_map(self, exc: Exception) -> None:
        return None

    async def _call(self, system_prompt: str, user_message: str) -> str:
        return json.dumps(self._response) if isinstance(self._response, dict) else ""

    async def _call_json(
        self, system_prompt: str, user_message: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.last_user_msg = user_message
        if isinstance(self._response, Exception):
            raise self._response
        if isinstance(self._response, dict):
            return self._response
        raise LLMResponseError("No response configured")


_VALID_STRATEGY = {
    "queries": [
        {
            "keywords": ["LLM", "medical imaging"],
            "synonym_map": [{"keyword": "LLM", "synonyms": ["large language model"]}],
            "boolean_query": "(LLM OR large language model) AND medical imaging",
        }
    ],
    "sources": ["serpapi_scholar"],
    "filters": {"year_from": 2020, "year_to": None, "language": None, "max_results": 100},
}

_INTENT = ParsedIntent(
    topic="LLM in medical imaging",
    concepts=["LLM", "medical imaging", "diagnosis"],
    intent_type=IntentType.SURVEY,
    constraints=SearchConstraints(year_from=2020),
)

_INPUT = QueryBuilderInput(intent=_INTENT)


class TestQueryBuilderBuild:
    @pytest.mark.asyncio
    async def test_build_basic(self):
        llm = MockLLM(_VALID_STRATEGY)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        assert len(result.queries) >= 1
        assert result.sources == ["serpapi_scholar"]
        assert result.queries[0].boolean_query != ""

    @pytest.mark.asyncio
    async def test_build_with_iteration(self):
        from paper_search.models import SearchStrategy, SearchQuery, UserFeedback

        prev_strategy = SearchStrategy(
            queries=[SearchQuery(keywords=["old"], synonym_map=[], boolean_query="old query")],
            sources=["serpapi_scholar"],
        )
        feedback = UserFeedback(
            marked_relevant=["paper1"],
            free_text_feedback="Need more focus on radiology",
        )
        input_with_history = QueryBuilderInput(
            intent=_INTENT,
            previous_strategies=[prev_strategy],
            user_feedback=feedback,
        )

        llm = MockLLM(_VALID_STRATEGY)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        await builder.build(input_with_history)

        # Verify user message contains iteration context
        assert "Previous strategies" in llm.last_user_msg
        assert "old query" in llm.last_user_msg
        assert "radiology" in llm.last_user_msg

    @pytest.mark.asyncio
    async def test_source_restriction(self):
        strategy_with_extra_sources = {
            **_VALID_STRATEGY,
            "sources": ["semantic_scholar", "pubmed", "serpapi_scholar"],
        }
        llm = MockLLM(strategy_with_extra_sources)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        assert result.sources == ["serpapi_scholar"]

    @pytest.mark.asyncio
    async def test_source_restriction_all_unavailable(self):
        strategy_no_valid = {**_VALID_STRATEGY, "sources": ["semantic_scholar"]}
        llm = MockLLM(strategy_no_valid)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        # Falls back to all available sources
        assert result.sources == ["serpapi_scholar"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self):
        llm = MockLLM(LLMError("API down"))
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        assert len(result.queries) == 1
        assert "LLM" in result.queries[0].boolean_query
        assert "medical imaging" in result.queries[0].boolean_query
        assert result.sources == ["serpapi_scholar"]
        assert result.filters.year_from == 2020

    @pytest.mark.asyncio
    async def test_fallback_on_validation_error(self):
        llm = MockLLM({"bad": "data"})
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        # Should fall back to deterministic strategy
        assert len(result.queries) == 1
        assert result.sources == ["serpapi_scholar"]

    @pytest.mark.asyncio
    async def test_sanitize_year_range(self):
        strategy_bad_years = {
            **_VALID_STRATEGY,
            "filters": {"year_from": 2025, "year_to": 2020, "max_results": 100},
        }
        llm = MockLLM(strategy_bad_years)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        assert result.filters.year_from == 2020
        assert result.filters.year_to == 2025

    @pytest.mark.asyncio
    async def test_sanitize_empty_queries(self):
        strategy_no_queries = {**_VALID_STRATEGY, "queries": []}
        llm = MockLLM(strategy_no_queries)
        builder = QueryBuilder(llm, available_sources=["serpapi_scholar"])
        result = await builder.build(_INPUT)

        # Should add fallback query
        assert len(result.queries) >= 1


class TestQueryBuilderPromptComposition:
    def test_general_domain(self):
        llm = MockLLM()
        builder = QueryBuilder(llm, domain="general")
        prompt = builder._compose_prompt()
        assert prompt == QUERY_BUILDING_SYSTEM

    def test_materials_science_domain(self):
        llm = MockLLM()
        builder = QueryBuilder(llm, domain="materials_science")
        prompt = builder._compose_prompt()
        assert prompt.startswith(QUERY_BUILDING_SYSTEM)
        assert "material families" in prompt
