"""paper-search: AI-powered academic paper search workflow system."""

from __future__ import annotations

from typing import TYPE_CHECKING

from paper_search.export import export_bibtex, export_json, export_markdown
from paper_search.models import (
    Paper,
    PaperCollection,
    ParsedIntent,
    SearchStrategy,
)

if TYPE_CHECKING:
    from paper_search.config import AppConfig


async def search(
    query: str,
    config: AppConfig | None = None,
    max_results: int = 100,
    domain: str = "general",
) -> PaperCollection:
    """One-line convenience: run full search pipeline with auto-approve.

    Args:
        query: Natural language search query.
        config: Optional AppConfig. If None, loads from environment.
        max_results: Maximum results to return.
        domain: Research domain ("general" or "materials_science").
    """
    from paper_search.config import load_config
    from paper_search.workflow import SearchWorkflow

    cfg = config or load_config()
    wf = SearchWorkflow.from_config(cfg)
    return await wf.run(query)


__all__ = [
    "Paper",
    "PaperCollection",
    "ParsedIntent",
    "SearchStrategy",
    "search",
    "export_json",
    "export_bibtex",
    "export_markdown",
]
