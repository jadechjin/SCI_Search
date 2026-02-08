# Design: Query Builder, Relevance Scorer, Deduplicator, Result Organizer, Searcher

## Architecture: 5 Skills in a Linear Pipeline

Each skill is a standalone class with a single async public method. Skills are composed by the workflow orchestrator (Phase 4). Each skill follows the established pattern from Phase 2.

## Locked Constraints

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| QueryBuilder queries | 2-4 per strategy | Balance recall vs API cost |
| QueryBuilder sources | Restricted to configured sources | Prevent hallucinated sources |
| QueryBuilder fallback | Deterministic `concepts AND` query | Graceful degradation on LLM failure |
| Searcher concurrency | asyncio.gather(return_exceptions=True) | Partial failure tolerance |
| Dedup algorithm pass | DOI → source_id → URL → exact normalized title | Fast exact matches first |
| Dedup LLM pass | Batch remaining titles+years → LLM groups duplicates | AI-based semantic matching |
| Dedup merge strategy | Keep richest record (most fields, highest citations) | Maximize data quality |
| Scorer batch size | 10 papers | Conservative token usage |
| Scorer truncation | title≤200, snippet≤500 chars | Stay within context limits |
| Scorer concurrency | Sequential batches | Avoid rate limits |
| Scorer prompt schema | `{"results": [...]}` wrapper (NOT top-level array) | Compatible with extract_json |
| Scorer anchor rubric | 1.0/0.7/0.3/0.0 examples in prompt | Consistent scoring calibration |
| Organizer relevance threshold | 0.3 default | Include tangentially related papers |
| Organizer sort | relevance desc → citations desc → year desc → title asc | Deterministic ordering |
| Organizer top_authors | Top 10 by frequency | Standard facet size |
| Organizer key_themes | Top 8 terms from high-score titles | Simple TF, no NLP dependency |
| Domain prompts | Same composition pattern as IntentParser | Consistency |

## File Touch List

| File | Change Type | Description |
|------|-------------|-------------|
| `src/paper_search/prompts/query_building.py` | **Rewrite** | Updated prompt with JSON object schema, domain hook |
| `src/paper_search/prompts/relevance_scoring.py` | **Rewrite** | Fix array→object wrapper, add anchor examples |
| `src/paper_search/prompts/dedup.py` | **New** | LLM dedup batch prompt |
| `src/paper_search/skills/query_builder.py` | **Rewrite** | Full implementation |
| `src/paper_search/skills/searcher.py` | **Rewrite** | Full implementation |
| `src/paper_search/skills/deduplicator.py` | **Rewrite** | Hybrid algorithm+LLM implementation |
| `src/paper_search/skills/relevance_scorer.py` | **Rewrite** | Full batch scoring implementation |
| `src/paper_search/skills/result_organizer.py` | **Rewrite** | Full implementation with facets |
| `tests/test_skills/test_query_builder.py` | **New** | QueryBuilder tests |
| `tests/test_skills/test_searcher.py` | **New** | Searcher tests |
| `tests/test_skills/test_deduplicator.py` | **New** | Deduplicator tests |
| `tests/test_skills/test_relevance_scorer.py` | **New** | RelevanceScorer tests |
| `tests/test_skills/test_result_organizer.py` | **New** | ResultOrganizer tests |

## Component Design

### QueryBuilder

```python
class QueryBuilder:
    def __init__(self, llm: LLMProvider, domain: str = "general",
                 available_sources: list[str] | None = None) -> None:
        self._llm = llm
        self._domain = domain
        self._available_sources = available_sources or ["serpapi_scholar"]

    def _compose_prompt(self) -> str:
        base = QUERY_BUILDING_SYSTEM
        domain_config = get_domain_config(self._domain)
        if domain_config:
            base += "\n\n" + domain_config.extra_intent_instructions
        return base

    def _format_user_message(self, input: QueryBuilderInput) -> str:
        # Format intent + previous_strategies + user_feedback as structured text
        # Include available_sources list

    async def build(self, input: QueryBuilderInput) -> SearchStrategy:
        prompt = self._compose_prompt()
        user_msg = self._format_user_message(input)
        schema = SearchStrategy.model_json_schema()
        try:
            result = await self._llm.complete_json(prompt, user_msg, schema=schema)
            strategy = SearchStrategy.model_validate(result)
            return self._sanitize(strategy)
        except (LLMError, ValidationError):
            return self._fallback_strategy(input)

    def _sanitize(self, strategy: SearchStrategy) -> SearchStrategy:
        # Intersect sources with available_sources
        # Clamp max_results, fix year_from > year_to
        # Ensure at least 1 query

    def _fallback_strategy(self, input: QueryBuilderInput) -> SearchStrategy:
        # Deterministic: concepts joined with AND as boolean_query
        # sources = self._available_sources
        # filters from intent.constraints
```

### Searcher

```python
class Searcher:
    def __init__(self, sources: list[SearchSource]) -> None:
        self._sources = {s.source_name: s for s in sources}

    async def search(self, strategy: SearchStrategy) -> list[RawPaper]:
        # Determine which sources to use (strategy.sources ∩ available)
        # If empty intersection, use all configured sources
        tasks = [source.search_advanced(strategy) for source in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Collect successful results, log exceptions
        # Flatten into single list
        return all_papers
```

### Deduplicator

```python
class Deduplicator:
    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    async def deduplicate(self, papers: list[RawPaper]) -> list[RawPaper]:
        if len(papers) <= 1:
            return papers
        # Pass 1: Algorithm-based exact matching
        groups = self._algorithm_pass(papers)
        # Pass 2: LLM-based semantic matching (if llm provided and ungrouped papers remain)
        if self._llm and len(groups.ungrouped) > 1:
            groups = await self._llm_pass(groups)
        # Merge each group: keep richest record
        return [self._merge_group(g) for g in groups]

    def _algorithm_pass(self, papers: list[RawPaper]) -> DedupGroups:
        # Step 1: Group by DOI (exact, case-insensitive)
        # Step 2: Group by source result_id or link URL
        # Step 3: Group by normalized title (lowercase, strip punctuation, collapse whitespace)
        # Remaining ungrouped papers → candidates for LLM pass

    async def _llm_pass(self, groups: DedupGroups) -> DedupGroups:
        # Send ungrouped paper titles+years to LLM
        # LLM returns groups of duplicate indices
        # Merge LLM groups into existing groups

    @staticmethod
    def _normalize_title(title: str) -> str:
        # Lowercase, strip punctuation, collapse whitespace

    @staticmethod
    def _merge_group(papers: list[RawPaper]) -> RawPaper:
        # Keep paper with most non-null fields
        # Prefer paper with DOI, with longer snippet, higher citation_count
```

### RelevanceScorer

```python
class RelevanceScorer:
    def __init__(self, llm: LLMProvider, batch_size: int = 10) -> None:
        self._llm = llm
        self._batch_size = batch_size

    async def score(self, papers: list[RawPaper], intent: ParsedIntent) -> list[ScoredPaper]:
        if not papers:
            return []
        batches = self._make_batches(papers)
        all_scored = []
        for batch in batches:
            scored = await self._score_batch(batch, intent)
            all_scored.extend(scored)
        return all_scored

    def _make_batches(self, papers: list[RawPaper]) -> list[list[RawPaper]]:
        # Split into chunks of batch_size

    async def _score_batch(self, batch: list[RawPaper], intent: ParsedIntent) -> list[ScoredPaper]:
        prompt = RELEVANCE_SCORING_SYSTEM
        user_msg = self._format_batch(batch, intent)
        try:
            result = await self._llm.complete_json(prompt, user_msg)
            return self._parse_scores(batch, result)
        except (LLMError, ValidationError):
            # Fallback: assign default low score
            return [self._default_score(p) for p in batch]

    def _format_batch(self, batch: list[RawPaper], intent: ParsedIntent) -> str:
        # Format: topic + concepts, then list of papers with id/title/snippet/year/venue
        # Truncate: title<=200, snippet<=500

    def _parse_scores(self, batch: list[RawPaper], result: dict) -> list[ScoredPaper]:
        # Extract result["results"], match by paper_id
        # Validate: score in [0,1], tags from PaperTag enum
        # Fill missing papers with default score
        # Clamp scores, sanitize tags

    @staticmethod
    def _default_score(paper: RawPaper) -> ScoredPaper:
        return ScoredPaper(paper=paper, relevance_score=0.0,
                          relevance_reason="Scoring unavailable", tags=[])
```

### ResultOrganizer

```python
class ResultOrganizer:
    def __init__(self, min_relevance: float = 0.3) -> None:
        self._min_relevance = min_relevance

    async def organize(self, papers: list[ScoredPaper], strategy: SearchStrategy,
                       original_query: str) -> PaperCollection:
        # Filter by min_relevance
        filtered = [p for p in papers if p.relevance_score >= self._min_relevance]
        # Sort: relevance desc → citations desc → year desc → title asc
        sorted_papers = self._sort(filtered)
        # Convert ScoredPaper → Paper
        final_papers = [self._to_paper(sp) for sp in sorted_papers]
        # Build facets
        facets = self._build_facets(final_papers)
        # Build metadata
        metadata = SearchMetadata(query=original_query, search_strategy=strategy,
                                  total_found=len(papers))
        return PaperCollection(metadata=metadata, papers=final_papers, facets=facets)

    def _sort(self, papers: list[ScoredPaper]) -> list[ScoredPaper]:
        return sorted(papers, key=lambda p: (
            -p.relevance_score,
            -p.paper.citation_count,
            -(p.paper.year or 0),
            p.paper.title.lower(),
        ))

    @staticmethod
    def _to_paper(sp: ScoredPaper) -> Paper:
        # Map ScoredPaper fields to Paper fields

    def _build_facets(self, papers: list[Paper]) -> Facets:
        # by_year: Counter of non-null years
        # by_venue: Counter of non-null venues (normalized)
        # top_authors: top 10 author names by frequency
        # key_themes: top 8 words from titles of papers with relevance_score >= 0.5
        #   (after removing stopwords, words < 3 chars)
```

### Prompt Templates

**query_building.py** (rewrite):
- Output schema: JSON object matching SearchStrategy model
- Include available sources list
- Include iteration context section (previous strategies, user feedback)
- Domain-composable like intent parsing

**relevance_scoring.py** (rewrite):
- Output schema: `{"results": [{"paper_id": "...", "relevance_score": 0.0, "relevance_reason": "...", "tags": [...]}]}`
- Anchor examples at 1.0/0.7/0.3/0.0
- Strict: score every input paper, no extra papers

**dedup.py** (new):
- Input: list of papers with id, title, year
- Output: `{"groups": [["id1", "id2"], ["id3"]], "reasoning": "..."}`
- Instruction: group papers that are likely the same work (same paper, preprint vs published, etc.)

## PBT Properties

See specs for detailed property-based testing invariants.
