"""Result organizer skill: ScoredPaper[] -> PaperCollection."""

from __future__ import annotations

from collections import Counter

from paper_search.models import (
    Author,
    Facets,
    Paper,
    PaperCollection,
    ScoredPaper,
    SearchMetadata,
    SearchStrategy,
)

_STOPWORDS = frozenset(
    "the a an in of on for and or to is are was were with by from at as "
    "its this that these those it be been has have had not but also can "
    "will may would could should into between their our them they than "
    "more most about over under such when where which what how other some "
    "all any each very only then so no".split()
)

_MIN_WORD_LEN = 3


class ResultOrganizer:
    """Sort, filter, group scored papers into final PaperCollection."""

    def __init__(self, min_relevance: float = 0.3) -> None:
        self._min_relevance = min_relevance

    async def organize(
        self,
        papers: list[ScoredPaper],
        strategy: SearchStrategy,
        original_query: str,
    ) -> PaperCollection:
        total_found = len(papers)

        # Filter by relevance threshold
        filtered = [
            p for p in papers if p.relevance_score >= self._min_relevance
        ]

        # Sort
        sorted_papers = self._sort(filtered)

        # Convert ScoredPaper → Paper
        final_papers = [self._to_paper(sp) for sp in sorted_papers]

        # Build facets
        facets = self._build_facets(final_papers)

        # Build metadata
        metadata = SearchMetadata(
            query=original_query,
            search_strategy=strategy,
            total_found=total_found,
        )

        return PaperCollection(
            metadata=metadata, papers=final_papers, facets=facets
        )

    @staticmethod
    def _sort(papers: list[ScoredPaper]) -> list[ScoredPaper]:
        return sorted(
            papers,
            key=lambda p: (
                -p.relevance_score,
                -p.paper.citation_count,
                -(p.paper.year or 0),
                p.paper.title.lower(),
            ),
        )

    @staticmethod
    def _to_paper(sp: ScoredPaper) -> Paper:
        p = sp.paper
        return Paper(
            id=p.id,
            doi=p.doi,
            title=p.title,
            authors=p.authors,
            abstract=p.abstract,
            year=p.year,
            venue=p.venue,
            source=p.source,
            citation_count=p.citation_count,
            relevance_score=sp.relevance_score,
            relevance_reason=sp.relevance_reason,
            tags=sp.tags,
            full_text_url=p.full_text_url,
            bibtex=p.bibtex,
        )

    @staticmethod
    def _build_facets(papers: list[Paper]) -> Facets:
        # by_year
        year_counter: Counter[int] = Counter()
        for p in papers:
            if p.year is not None:
                year_counter[p.year] += 1

        # by_venue (title-cased normalization)
        venue_counter: Counter[str] = Counter()
        for p in papers:
            if p.venue:
                venue_counter[p.venue.strip().title()] += 1

        # top_authors (top 10 by frequency)
        author_counter: Counter[str] = Counter()
        for p in papers:
            for a in p.authors:
                author_counter[a.name] += 1
        top_authors = [
            name for name, _ in author_counter.most_common(10)
        ]

        # key_themes (top 8 words from high-relevance paper titles)
        word_counter: Counter[str] = Counter()
        for p in papers:
            if p.relevance_score >= 0.5:
                words = p.title.lower().split()
                for w in words:
                    cleaned = w.strip(".,;:!?()[]{}\"'")
                    if (
                        len(cleaned) >= _MIN_WORD_LEN
                        and cleaned not in _STOPWORDS
                    ):
                        word_counter[cleaned] += 1
        key_themes = [
            word for word, _ in word_counter.most_common(8)
        ]

        return Facets(
            by_year=dict(year_counter),
            by_venue=dict(venue_counter),
            top_authors=top_authors,
            key_themes=key_themes,
        )
