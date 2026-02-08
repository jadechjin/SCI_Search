"""Tests for ResultOrganizer skill."""

from __future__ import annotations

import pytest

from paper_search.models import (
    Author,
    PaperTag,
    RawPaper,
    ScoredPaper,
    SearchConstraints,
    SearchQuery,
    SearchStrategy,
)
from paper_search.skills.result_organizer import ResultOrganizer


def _scored(
    title: str,
    score: float,
    citations: int = 0,
    year: int | None = None,
    venue: str | None = None,
    authors: list[Author] | None = None,
    tags: list[PaperTag] | None = None,
) -> ScoredPaper:
    paper = RawPaper(
        title=title,
        source="test",
        citation_count=citations,
        year=year,
        venue=venue,
        authors=authors or [],
    )
    return ScoredPaper(
        paper=paper,
        relevance_score=score,
        relevance_reason=f"Score {score}",
        tags=tags or [],
    )


_STRATEGY = SearchStrategy(
    queries=[SearchQuery(keywords=["test"], synonym_map=[], boolean_query="test")],
    sources=["serpapi_scholar"],
)


class TestResultOrganizerFilter:
    @pytest.mark.asyncio
    async def test_filter_by_relevance(self):
        papers = [
            _scored("High", 0.8),
            _scored("Medium", 0.5),
            _scored("Low", 0.2),
            _scored("Very Low", 0.1),
        ]
        org = ResultOrganizer(min_relevance=0.3)
        result = await org.organize(papers, _STRATEGY, "test query")

        assert len(result.papers) == 2
        titles = [p.title for p in result.papers]
        assert "High" in titles
        assert "Medium" in titles

    @pytest.mark.asyncio
    async def test_all_filtered_out(self):
        papers = [_scored("Low", 0.1), _scored("Lower", 0.05)]
        org = ResultOrganizer(min_relevance=0.3)
        result = await org.organize(papers, _STRATEGY, "test query")

        assert len(result.papers) == 0
        assert result.metadata.total_found == 2  # Original count

    @pytest.mark.asyncio
    async def test_empty_input(self):
        org = ResultOrganizer()
        result = await org.organize([], _STRATEGY, "test query")

        assert len(result.papers) == 0
        assert result.metadata.total_found == 0


class TestResultOrganizerSort:
    @pytest.mark.asyncio
    async def test_sort_order(self):
        papers = [
            _scored("A", 0.8, citations=10, year=2020),
            _scored("B", 0.8, citations=20, year=2021),
            _scored("C", 0.9, citations=5, year=2022),
        ]
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize(papers, _STRATEGY, "test")

        # C (0.9) first, then B (0.8, 20 cits), then A (0.8, 10 cits)
        assert result.papers[0].title == "C"
        assert result.papers[1].title == "B"
        assert result.papers[2].title == "A"


class TestResultOrganizerFacets:
    @pytest.mark.asyncio
    async def test_facets_by_year(self):
        papers = [
            _scored("A", 0.8, year=2020),
            _scored("B", 0.8, year=2020),
            _scored("C", 0.8, year=2021),
            _scored("D", 0.8, year=None),
        ]
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize(papers, _STRATEGY, "test")

        assert result.facets.by_year == {2020: 2, 2021: 1}

    @pytest.mark.asyncio
    async def test_facets_by_venue(self):
        papers = [
            _scored("A", 0.8, venue="Nature"),
            _scored("B", 0.8, venue="nature"),
            _scored("C", 0.8, venue="Science"),
            _scored("D", 0.8, venue=None),
        ]
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize(papers, _STRATEGY, "test")

        assert result.facets.by_venue == {"Nature": 2, "Science": 1}

    @pytest.mark.asyncio
    async def test_facets_top_authors(self):
        papers = [
            _scored("A", 0.8, authors=[Author(name="Alice"), Author(name="Bob")]),
            _scored("B", 0.8, authors=[Author(name="Alice"), Author(name="Charlie")]),
            _scored("C", 0.8, authors=[Author(name="Alice")]),
        ]
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize(papers, _STRATEGY, "test")

        assert result.facets.top_authors[0] == "Alice"
        assert len(result.facets.top_authors) <= 10

    @pytest.mark.asyncio
    async def test_facets_key_themes(self):
        papers = [
            _scored("Large Language Models Applications", 0.8),
            _scored("Language Models Performance Evaluation", 0.7),
            _scored("Irrelevant Low Score Paper", 0.2),  # Below 0.5 threshold
        ]
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize(papers, _STRATEGY, "test")

        # "language" and "models" should appear (from high-score papers)
        assert len(result.facets.key_themes) <= 8
        themes_lower = [t.lower() for t in result.facets.key_themes]
        assert "language" in themes_lower
        assert "models" in themes_lower


class TestResultOrganizerConversion:
    @pytest.mark.asyncio
    async def test_scored_to_paper(self):
        sp = _scored(
            "Test Paper",
            score=0.75,
            citations=42,
            year=2023,
            venue="Nature",
            authors=[Author(name="Alice")],
            tags=[PaperTag.METHOD],
        )
        org = ResultOrganizer(min_relevance=0.0)
        result = await org.organize([sp], _STRATEGY, "test")

        p = result.papers[0]
        assert p.title == "Test Paper"
        assert p.relevance_score == 0.75
        assert p.citation_count == 42
        assert p.year == 2023
        assert p.venue == "Nature"
        assert len(p.authors) == 1
        assert p.tags == [PaperTag.METHOD]
