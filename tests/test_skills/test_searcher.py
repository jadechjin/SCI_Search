"""Tests for Searcher skill."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from paper_search.models import (
    RawPaper,
    SearchConstraints,
    SearchQuery,
    SearchStrategy,
)
from paper_search.skills.searcher import Searcher
from paper_search.sources.base import SearchSource


class MockSource(SearchSource):
    def __init__(self, name: str, papers: list[RawPaper] | Exception) -> None:
        self._name = name
        self._papers = papers

    @property
    def source_name(self) -> str:
        return self._name

    async def search(self, query: str, **kwargs) -> list[RawPaper]:
        if isinstance(self._papers, Exception):
            raise self._papers
        return self._papers

    async def search_advanced(self, strategy: SearchStrategy) -> list[RawPaper]:
        if isinstance(self._papers, Exception):
            raise self._papers
        return self._papers


def _make_strategy(sources: list[str] | None = None, queries: list[SearchQuery] | None = None) -> SearchStrategy:
    return SearchStrategy(
        queries=[SearchQuery(keywords=["test"], synonym_map=[], boolean_query="test")] if queries is None else queries,
        sources=sources or ["source_a"],
    )


def _make_paper(title: str, source: str = "test") -> RawPaper:
    return RawPaper(title=title, source=source)


class TestSearcher:
    @pytest.mark.asyncio
    async def test_search_single_source(self):
        papers = [_make_paper("Paper A", "source_a")]
        src = MockSource("source_a", papers)
        searcher = Searcher([src])

        result = await searcher.search(_make_strategy(["source_a"]))
        assert len(result) == 1
        assert result[0].title == "Paper A"

    @pytest.mark.asyncio
    async def test_search_missing_source_fallback(self):
        papers = [_make_paper("Paper B", "source_a")]
        src = MockSource("source_a", papers)
        searcher = Searcher([src])

        # Strategy asks for unavailable source → falls back to configured
        result = await searcher.search(_make_strategy(["nonexistent"]))
        assert len(result) == 1
        assert result[0].title == "Paper B"

    @pytest.mark.asyncio
    async def test_search_partial_failure(self):
        papers_a = [_make_paper("Paper A", "source_a")]
        src_a = MockSource("source_a", papers_a)
        src_b = MockSource("source_b", RuntimeError("connection failed"))
        searcher = Searcher([src_a, src_b])

        result = await searcher.search(_make_strategy(["source_a", "source_b"]))
        assert len(result) == 1
        assert result[0].title == "Paper A"

    @pytest.mark.asyncio
    async def test_search_empty_queries(self):
        src = MockSource("source_a", [_make_paper("Paper A")])
        searcher = Searcher([src])

        result = await searcher.search(_make_strategy(queries=[]))
        assert result == []

    @pytest.mark.asyncio
    async def test_search_all_fail(self):
        src_a = MockSource("source_a", RuntimeError("fail"))
        src_b = MockSource("source_b", RuntimeError("fail"))
        searcher = Searcher([src_a, src_b])

        result = await searcher.search(_make_strategy(["source_a", "source_b"]))
        assert result == []
