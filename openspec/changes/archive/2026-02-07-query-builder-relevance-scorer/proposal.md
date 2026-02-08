# Proposal: Query Builder, Relevance Scorer, Deduplicator, Result Organizer, Searcher

## Problem
Phase 2 delivered LLM providers + IntentParser. The system can now parse user intent into `ParsedIntent`. Phase 3 must build the remaining pipeline skills that transform parsed intent into a scored, organized `PaperCollection`:

```
ParsedIntent → [QueryBuilder] → SearchStrategy
                                      ↓
                                  [Searcher] → RawPaper[]
                                      ↓
                                [Deduplicator] → RawPaper[] (deduped)
                                      ↓
                            [RelevanceScorer] → ScoredPaper[]
                                      ↓
                            [ResultOrganizer] → PaperCollection
```

## Scope
5 skills to implement:
1. **QueryBuilder**: LLM-driven `ParsedIntent → SearchStrategy` with iteration support
2. **Searcher**: Multi-source parallel search `SearchStrategy → RawPaper[]`
3. **Deduplicator**: Hybrid algorithm+LLM dedup `RawPaper[] → RawPaper[]`
4. **RelevanceScorer**: LLM batch scoring `RawPaper[] → ScoredPaper[]`
5. **ResultOrganizer**: Algorithm-driven sort/filter/facets `ScoredPaper[] → PaperCollection`

## Constraints Discovered

### C1: SerpAPI data gaps
- SerpAPI does NOT return DOI, abstract, or bibtex
- Only title, snippet, publication_info.summary, cited_by.total, link, result_id
- Dedup cannot rely on DOI; title+year is primary signal
- Relevance scoring uses title+snippet (not abstract)

### C2: extract_json returns dict only
- Current `extract_json()` only returns `dict[str, Any]`
- Relevance scoring prompt currently asks for top-level JSON array → MUST wrap in `{"results": [...]}`
- All LLM outputs must be JSON objects, never top-level arrays

### C3: Available sources
- Currently only `serpapi_scholar` is implemented
- QueryBuilder must constrain output sources to configured/available sources
- Searcher must handle single-source gracefully, be extensible for future sources

### C4: Deduplicator uses AI judgment (user decision)
- User explicitly requested AI-based dedup instead of fuzzy string matching
- Design: hybrid algorithm-first (DOI, source ID, URL, exact title) + LLM batch for remaining
- LLM receives paper titles+years in a batch → identifies duplicate groups
- Keep richest record from each group (most fields populated, highest citation count)

### C5: Batch scoring constraints
- Batch size: 10 papers per LLM call (conservative for token management)
- Include in prompt: title, snippet, year, venue (NOT citation_count — that's metadata, not content)
- Truncation: title max 200 chars, snippet max 500 chars
- Sequential batch processing (no parallel LLM calls to avoid rate limits)
- Anchor examples in prompt: 1.0, 0.7, 0.3, 0.0 rubric

### C6: ResultOrganizer parameters
- Relevance threshold: 0.3 default (configurable)
- Sort order: relevance_score desc → citation_count desc → year desc → title asc
- Facets: by_year (count), by_venue (count), top_authors (top 10 by freq), key_themes (top 8 terms from high-relevance titles)
- key_themes: simple word frequency from titles of papers with score >= 0.5, exclude stopwords

### C7: QueryBuilder constraints
- Generate 2-4 queries per strategy
- Sources restricted to available/configured source names
- Iteration support: previous_strategies + user_feedback formatted as compact JSON in user message
- Fallback on LLM failure: deterministic strategy from intent.concepts joined with AND
- Domain prompt composition: same pattern as IntentParser (base + domain extra)

### C8: Searcher design
- Execute sources in parallel via asyncio.gather(return_exceptions=True)
- Partial-failure: return successful source results, log errors
- If strategy lists unavailable sources, fall back to all enabled configured sources

## Success Criteria
- All 5 skills pass unit tests with mocked LLM/source dependencies
- Pipeline data flow is type-safe: each skill's output matches next skill's input
- Existing 63 tests continue passing
- New prompt templates produce valid JSON parseable by extract_json

## Risks
- R1: LLM dedup may hallucinate groupings (mitigate: algorithm-first pass, LLM only for remaining)
- R2: Batch scoring may miss papers or return mismatched IDs (mitigate: strict validation + fallback defaults)
- R3: QueryBuilder may generate bad boolean queries for Google Scholar (mitigate: validate structure, fallback)
