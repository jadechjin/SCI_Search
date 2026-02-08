"""Multi-source searcher skill: SearchStrategy -> RawPaper[]."""

from __future__ import annotations

import asyncio
import logging

from paper_search.models import RawPaper, SearchStrategy
from paper_search.sources.base import SearchSource

logger = logging.getLogger(__name__)


class Searcher:
    """Execute search across multiple sources in parallel."""

    def __init__(self, sources: list[SearchSource]) -> None:
        self._sources = {s.source_name: s for s in sources}

    async def search(self, strategy: SearchStrategy) -> list[RawPaper]:
        if not strategy.queries:
            return []

        # Select sources: strategy.sources ∩ available, or all if empty intersection
        selected = [
            self._sources[s]
            for s in strategy.sources
            if s in self._sources
        ]
        if not selected:
            selected = list(self._sources.values())
        if not selected:
            return []

        # Execute all sources in parallel
        tasks = [src.search_advanced(strategy) for src in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful results
        all_papers: list[RawPaper] = []
        for src, result in zip(selected, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Source '%s' failed: %s", src.source_name, result
                )
            else:
                all_papers.extend(result)

        return all_papers
