"""Search source adapter abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from paper_search.models import RawPaper, SearchStrategy


class SearchSource(ABC):
    """Abstract base class for search data sources.

    Each source adapter translates our internal query format
    into the specific API's syntax and normalizes the response
    into RawPaper objects.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source (e.g. 'serpapi_scholar')."""
        ...

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[RawPaper]:
        """Simple keyword search."""
        ...

    @abstractmethod
    async def search_advanced(self, strategy: SearchStrategy) -> list[RawPaper]:
        """Advanced search using a full SearchStrategy."""
        ...
