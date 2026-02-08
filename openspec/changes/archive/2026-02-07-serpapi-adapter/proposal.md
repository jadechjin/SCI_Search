# Proposal: SerpAPI Google Scholar Adapter

## Summary
Implement the SerpAPI Google Scholar search source adapter — the first concrete data source for the paper search workflow. This adapter translates search queries into SerpAPI HTTP calls and normalizes Google Scholar responses into `RawPaper` objects matching our data model.

## Motivation
Phase 0 established the project skeleton with abstract interfaces. Phase 1 delivers the first working vertical slice: a real API call that returns structured paper data. SerpAPI is the only data source currently available (user has API key).

## Scope

### In Scope
- `SerpAPIScholarSource` implementation (async, httpx-based)
- `publication_info.summary` parser (authors, year, venue extraction)
- DOI extraction from URLs/snippets
- Pagination (max 20/page, configurable total)
- Rate limiting (2 req/sec via async lock)
- Retry with exponential backoff (429/500/503 only)
- Factory wiring update to pass config
- Unit tests with captured response fixtures
- Integration smoke test (optional, requires live API key)

### Out of Scope
- Other data sources (Semantic Scholar, OpenAlex, arXiv) — Phase 2+
- LLM-based intent parsing or relevance scoring — Phase 2+
- Workflow orchestration — Phase 4
- BibTeX retrieval via Cite API — deferred enrichment
- Full abstract retrieval — not available from SerpAPI

## User Impact
After this change, developers can run:
```python
source = SerpAPIScholarSource(api_key="...", rate_limit_rps=2.0)
papers = await source.search("large language model medical imaging")
# Returns: list[RawPaper] with title, snippet, authors, year, venue, citation_count
```

## Risks
1. `publication_info.summary` format varies widely — parsing will be heuristic, some fields will be None
2. SerpAPI free tier has 100 searches/month — testing budget is limited
3. Google Scholar results lack DOI and abstract — downstream modules must handle nullable fields
