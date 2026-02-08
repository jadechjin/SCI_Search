"""Search source factory."""

from __future__ import annotations

from paper_search.config import SearchSourceConfig
from paper_search.sources.base import SearchSource


def create_source(config: SearchSourceConfig) -> SearchSource:
    """Create a search source adapter from configuration."""
    match config.name:
        case "serpapi_scholar":
            from paper_search.sources.serpapi_scholar import SerpAPIScholarSource

            return SerpAPIScholarSource(
                api_key=config.api_key,
                rate_limit_rps=config.rate_limit,
            )
        case _:
            raise ValueError(f"Unknown search source: {config.name}")
