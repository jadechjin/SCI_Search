"""Query builder skill: ParsedIntent -> SearchStrategy."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError
from paper_search.models import (
    QueryBuilderInput,
    SearchConstraints,
    SearchQuery,
    SearchStrategy,
)
from paper_search.prompts.domains import get_domain_config
from paper_search.prompts.query_building import QUERY_BUILDING_SYSTEM

logger = logging.getLogger(__name__)


class QueryBuilder:
    """Build search strategies from parsed intent, with iteration support."""

    def __init__(
        self,
        llm: LLMProvider,
        domain: str = "general",
        available_sources: list[str] | None = None,
    ) -> None:
        self._llm = llm
        self._domain = domain
        self._available_sources = available_sources or ["serpapi_scholar"]

    def _compose_prompt(self) -> str:
        base = QUERY_BUILDING_SYSTEM
        domain_config = get_domain_config(self._domain)
        if domain_config:
            base += "\n\n" + domain_config.extra_intent_instructions
        return base

    def _format_user_message(self, input: QueryBuilderInput) -> str:
        intent = input.intent
        parts = [
            f"Topic: {intent.topic}",
            f"Concepts: {', '.join(intent.concepts)}",
            f"Intent type: {intent.intent_type.value}",
            f"Constraints: year_from={intent.constraints.year_from}, "
            f"year_to={intent.constraints.year_to}, "
            f"language={intent.constraints.language}, "
            f"max_results={intent.constraints.max_results}",
            f"Available sources: {', '.join(self._available_sources)}",
        ]

        if input.previous_strategies:
            strategies_summary = []
            for i, s in enumerate(input.previous_strategies, 1):
                queries_str = "; ".join(q.boolean_query for q in s.queries)
                strategies_summary.append(f"  Strategy {i}: {queries_str}")
            parts.append(
                "Previous strategies (avoid repeating):\n"
                + "\n".join(strategies_summary)
            )

        if input.user_feedback:
            fb = input.user_feedback
            feedback_parts = []
            if fb.marked_relevant:
                feedback_parts.append(
                    f"  Papers marked relevant: {fb.marked_relevant}"
                )
            if fb.marked_irrelevant:
                feedback_parts.append(
                    f"  Papers marked irrelevant: {fb.marked_irrelevant}"
                )
            if fb.free_text_feedback:
                feedback_parts.append(
                    f"  User comment: {fb.free_text_feedback}"
                )
            if feedback_parts:
                parts.append(
                    "User feedback:\n" + "\n".join(feedback_parts)
                )

        return "\n".join(parts)

    async def build(self, input: QueryBuilderInput) -> SearchStrategy:
        prompt = self._compose_prompt()
        user_msg = self._format_user_message(input)
        schema = SearchStrategy.model_json_schema()
        try:
            result = await self._llm.complete_json(prompt, user_msg, schema=schema)
            strategy = SearchStrategy.model_validate(result)
            return self._sanitize(strategy, input)
        except (LLMError, ValidationError) as exc:
            logger.warning("QueryBuilder LLM failed, using fallback: %s", exc)
            return self._fallback_strategy(input)

    def _sanitize(
        self, strategy: SearchStrategy, input: QueryBuilderInput
    ) -> SearchStrategy:
        # Restrict sources to available
        valid_sources = [
            s for s in strategy.sources if s in self._available_sources
        ]
        if not valid_sources:
            valid_sources = list(self._available_sources)
        strategy.sources = valid_sources

        # Fix year range
        f = strategy.filters
        if f.year_from is not None and f.year_to is not None:
            if f.year_from > f.year_to:
                f.year_from, f.year_to = f.year_to, f.year_from

        # Clamp max_results
        f.max_results = max(1, min(200, f.max_results))

        # Ensure at least one query
        if not strategy.queries:
            strategy.queries = [self._make_fallback_query(input)]

        return strategy

    def _fallback_strategy(self, input: QueryBuilderInput) -> SearchStrategy:
        return SearchStrategy(
            queries=[self._make_fallback_query(input)],
            sources=list(self._available_sources),
            filters=SearchConstraints(
                year_from=input.intent.constraints.year_from,
                year_to=input.intent.constraints.year_to,
                language=input.intent.constraints.language,
                max_results=input.intent.constraints.max_results,
            ),
        )

    @staticmethod
    def _make_fallback_query(input: QueryBuilderInput) -> SearchQuery:
        concepts = input.intent.concepts or [input.intent.topic]
        return SearchQuery(
            keywords=concepts,
            synonym_map=[],
            boolean_query=" AND ".join(concepts),
        )
