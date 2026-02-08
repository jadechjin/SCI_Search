"""Tests for core data models."""

from paper_search.models import (
    Author,
    Facets,
    IntentType,
    Paper,
    PaperCollection,
    PaperTag,
    ParsedIntent,
    RawPaper,
    ScoredPaper,
    SearchConstraints,
    SearchMetadata,
    SearchQuery,
    SearchStrategy,
)


def test_parsed_intent_defaults():
    intent = ParsedIntent(
        topic="LLM in medical imaging",
        concepts=["LLM", "medical imaging"],
        intent_type=IntentType.SURVEY,
    )
    assert intent.constraints.max_results == 100
    assert intent.constraints.year_from is None


def test_raw_paper_has_auto_id():
    p = RawPaper(title="Test Paper", source="serpapi_scholar")
    assert p.id is not None
    assert len(p.id) > 0


def test_scored_paper_score_bounds():
    raw = RawPaper(title="Test", source="test")
    scored = ScoredPaper(
        paper=raw,
        relevance_score=0.85,
        relevance_reason="Highly relevant",
        tags=[PaperTag.METHOD],
    )
    assert 0.0 <= scored.relevance_score <= 1.0


def test_paper_collection_creation():
    strategy = SearchStrategy(
        queries=[SearchQuery(keywords=["test"], boolean_query="test")],
        sources=["serpapi_scholar"],
    )
    metadata = SearchMetadata(
        query="test query",
        search_strategy=strategy,
        total_found=1,
    )
    paper = Paper(
        id="p1",
        title="Test Paper",
        authors=[Author(name="J. Doe")],
        source="serpapi_scholar",
    )
    collection = PaperCollection(
        metadata=metadata,
        papers=[paper],
    )
    assert len(collection.papers) == 1
    assert collection.facets.by_year == {}


def test_search_constraints_with_values():
    c = SearchConstraints(year_from=2020, year_to=2025, language="en", max_results=50)
    assert c.year_from == 2020
    assert c.max_results == 50


def test_paper_serialization_roundtrip():
    paper = Paper(
        id="p1",
        doi="10.1234/test",
        title="Test Paper",
        authors=[Author(name="J. Doe", author_id="abc123")],
        year=2024,
        venue="Nature",
        source="serpapi_scholar",
        citation_count=42,
        relevance_score=0.9,
        relevance_reason="Directly relevant",
        tags=[PaperTag.EMPIRICAL],
    )
    data = paper.model_dump()
    restored = Paper.model_validate(data)
    assert restored.doi == "10.1234/test"
    assert restored.tags == [PaperTag.EMPIRICAL]
