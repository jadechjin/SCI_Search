# Tasks: Query Builder, Relevance Scorer, Deduplicator, Result Organizer, Searcher

All decisions are locked in `design.md`. Each task is pure mechanical execution.

---

## Task 1: Update query building prompt [DONE]

**File**: `src/paper_search/prompts/query_building.py` (REWRITE)

Rewrite `QUERY_BUILDING_SYSTEM` prompt:
- Output schema: JSON object matching `SearchStrategy` model
- Include `{available_sources}` placeholder marker for the user message
- Add instruction: "Generate 2-4 queries. Use only sources from the provided list."
- Add instruction for iteration: "If previous strategies and feedback are provided, adjust."
- Add instruction: "boolean_query should use simple AND/OR syntax compatible with Google Scholar"

**Verify**: Import without error.

---

## Task 2: Update relevance scoring prompt [DONE]

**File**: `src/paper_search/prompts/relevance_scoring.py` (REWRITE)

Rewrite `RELEVANCE_SCORING_SYSTEM` prompt:
- Fix output schema: `{"results": [{"paper_id": "...", "relevance_score": 0.0, "relevance_reason": "...", "tags": [...]}]}`
- Add anchor examples: 1.0 = "directly addresses the exact research question", 0.7 = "closely related", 0.3 = "tangentially related", 0.0 = "unrelated"
- Add instruction: "Score EVERY input paper. Do not skip or add papers."
- Tags must be from: `method, review, empirical, theoretical, dataset`

**Verify**: Import without error.

---

## Task 3: Create dedup prompt [DONE]

**File**: `src/paper_search/prompts/dedup.py` (NEW)

Create `DEDUP_SYSTEM` prompt:
- Input: list of papers with id, title, year
- Output schema: `{"groups": [["id1", "id2"], ["id3", "id4"]], "singles": ["id5", "id6"]}`
- Instruction: "Group papers that are the same work (preprint vs published, different title phrasing, etc.)"
- Instruction: "If unsure, keep papers separate (prefer false negatives over false positives)"

**Verify**: Import without error.

---

## Task 4: Implement QueryBuilder [DONE]

**File**: `src/paper_search/skills/query_builder.py` (REWRITE)

Constructor: `__init__(self, llm: LLMProvider, domain: str = "general", available_sources: list[str] | None = None)`

`_compose_prompt() -> str`: Base prompt + domain extra (same pattern as IntentParser)

`_format_user_message(input: QueryBuilderInput) -> str`:
- Format intent as: "Topic: {topic}\nConcepts: {concepts}\nIntent type: {intent_type}\nConstraints: {constraints}"
- If previous_strategies: append "Previous strategies tried: {compact_json}"
- If user_feedback: append "User feedback: {feedback}"
- Append "Available sources: {available_sources}"

`async build(input: QueryBuilderInput) -> SearchStrategy`:
1. Compose prompt + user message
2. Call `llm.complete_json(prompt, user_msg, schema=SearchStrategy.model_json_schema())`
3. `SearchStrategy.model_validate(result)`
4. `_sanitize(strategy)`
5. On LLMError or ValidationError → `_fallback_strategy(input)`

`_sanitize(strategy: SearchStrategy) -> SearchStrategy`:
- `strategy.sources = [s for s in strategy.sources if s in self._available_sources] or self._available_sources`
- If year_from > year_to: swap
- If no queries: add fallback query
- Clamp max_results to 1-200 range

`_fallback_strategy(input: QueryBuilderInput) -> SearchStrategy`:
- One query: keywords=intent.concepts, boolean_query=" AND ".join(intent.concepts)
- sources=self._available_sources
- filters from intent.constraints

**Verify**: Import + basic instantiation.

---

## Task 5: Implement Searcher [DONE]

**File**: `src/paper_search/skills/searcher.py` (REWRITE)

Constructor: `__init__(self, sources: list[SearchSource])`
- Store as dict: `{s.source_name: s for s in sources}`

`async search(self, strategy: SearchStrategy) -> list[RawPaper]`:
1. `selected = [self._sources[s] for s in strategy.sources if s in self._sources]`
2. If empty: `selected = list(self._sources.values())`
3. If no sources at all or no queries: return []
4. `tasks = [src.search_advanced(strategy) for src in selected]`
5. `results = await asyncio.gather(*tasks, return_exceptions=True)`
6. Collect successful results (flatten), skip exceptions
7. Return all papers

**Verify**: Import + instantiation with mock source.

---

## Task 6: Implement Deduplicator [DONE]

**File**: `src/paper_search/skills/deduplicator.py` (REWRITE)

Constructor: `__init__(self, llm: LLMProvider | None = None)`

`async deduplicate(self, papers: list[RawPaper]) -> list[RawPaper]`:
1. If len <= 1: return papers
2. Algorithm pass → group duplicates
3. If self._llm and ungrouped papers > 1: LLM pass
4. Merge each group → return list

`_algorithm_pass(papers) -> tuple[list[list[RawPaper]], list[RawPaper]]`:
- Build union-find or group dict
- Pass 1: Group by DOI (lowercase, strip) — skip None
- Pass 2: Group by raw_data["result_id"] — skip missing
- Pass 3: Group by full_text_url — skip None
- Pass 4: Group by _normalize_title(title) — exact match
- Return (groups, ungrouped)

`async _llm_pass(ungrouped: list[RawPaper]) -> list[list[RawPaper]]`:
- Format papers as: `[{"id": p.id, "title": p.title, "year": p.year}, ...]`
- Call `self._llm.complete_json(DEDUP_SYSTEM, formatted_papers)`
- Parse result["groups"] → map IDs to papers
- On failure: return each paper as its own group

`@staticmethod _normalize_title(title: str) -> str`:
- `title.lower().strip()`
- Remove punctuation: `re.sub(r'[^\w\s]', '', ...)`
- Collapse whitespace: `re.sub(r'\s+', ' ', ...)`

`@staticmethod _merge_group(papers: list[RawPaper]) -> RawPaper`:
- Score each paper: +1 for each non-None field (doi, snippet, year, venue, full_text_url)
- Pick paper with highest score; on tie, highest citation_count
- From other papers in group: fill any None fields from their values
- Set citation_count = max across group

**Verify**: Import + basic dedup of exact-title duplicates.

---

## Task 7: Implement RelevanceScorer [DONE]

**File**: `src/paper_search/skills/relevance_scorer.py` (REWRITE)

Constructor: `__init__(self, llm: LLMProvider, batch_size: int = 10)`

`async score(papers, intent) -> list[ScoredPaper]`:
1. If empty: return []
2. Split into batches of batch_size
3. For each batch: `await _score_batch(batch, intent)`
4. Collect all scored papers

`_make_batches(papers) -> list[list[RawPaper]]`:
- `[papers[i:i+batch_size] for i in range(0, len(papers), batch_size)]`

`async _score_batch(batch, intent) -> list[ScoredPaper]`:
1. Format prompt + user message
2. Call `llm.complete_json(prompt, user_msg)`
3. Parse result["results"] → match to batch papers by paper_id
4. On LLMError: return default scores for all in batch

`_format_batch(batch, intent) -> str`:
- "Research topic: {intent.topic}\nKey concepts: {', '.join(intent.concepts)}\n\nPapers to score:"
- For each paper: "- ID: {id}\n  Title: {title[:200]}\n  Snippet: {snippet[:500]}\n  Year: {year}\n  Venue: {venue}"

`_parse_scores(batch, result) -> list[ScoredPaper]`:
- Build id→RawPaper map from batch
- For each item in result["results"]:
  - Match paper_id to batch paper
  - Clamp score to [0.0, 1.0]
  - Filter tags to valid PaperTag enum values
  - Create ScoredPaper
- For any batch papers not in result: create with default score
- Return all scored papers in batch order

`@staticmethod _default_score(paper) -> ScoredPaper`:
- ScoredPaper(paper=paper, relevance_score=0.0, relevance_reason="Scoring unavailable", tags=[])

**Verify**: Import + instantiation with mock LLM.

---

## Task 8: Implement ResultOrganizer [DONE]

**File**: `src/paper_search/skills/result_organizer.py` (REWRITE)

Constructor: `__init__(self, min_relevance: float = 0.3)`

`async organize(papers, strategy, original_query) -> PaperCollection`:
1. Filter: `[p for p in papers if p.relevance_score >= self._min_relevance]`
2. Sort: `_sort(filtered)`
3. Convert: `[_to_paper(sp) for sp in sorted_papers]`
4. Facets: `_build_facets(final_papers)`
5. Metadata: `SearchMetadata(query=original_query, search_strategy=strategy, total_found=len(papers))`
6. Return PaperCollection(metadata, papers, facets)

`_sort(papers) -> list[ScoredPaper]`:
- `sorted(papers, key=lambda p: (-p.relevance_score, -p.paper.citation_count, -(p.paper.year or 0), p.paper.title.lower()))`

`@staticmethod _to_paper(sp: ScoredPaper) -> Paper`:
- Map all fields from sp.paper + sp.relevance_score, sp.relevance_reason, sp.tags

`_build_facets(papers: list[Paper]) -> Facets`:
- `by_year`: Counter of p.year for p.year is not None
- `by_venue`: Counter of _normalize_venue(p.venue) for p.venue is not None
  - `_normalize_venue`: title case
- `top_authors`: flatten all p.authors[].name, Counter, .most_common(10) → names list
- `key_themes`: for papers with relevance_score >= 0.5:
  - Split titles into words, lowercase
  - Remove stopwords (basic English set: the, a, an, in, of, on, for, and, or, to, is, are, with, by, from, at, as, its, this, that, etc.)
  - Remove words < 3 chars
  - Counter.most_common(8) → list of words

**Verify**: Import + basic organization of sample data.

---

## Task 9: Write QueryBuilder tests [DONE]

**File**: `tests/test_skills/test_query_builder.py` (NEW)

Tests (all with mocked LLM):
1. `test_build_basic` — mock returns valid SearchStrategy JSON → returns SearchStrategy
2. `test_build_with_iteration` — mock with previous_strategies → verify user message contains them
3. `test_source_restriction` — mock returns extra sources → sanitized to available only
4. `test_fallback_on_llm_error` — mock raises LLMError → returns deterministic fallback
5. `test_fallback_on_validation_error` — mock returns garbage → returns fallback
6. `test_sanitize_year_range` — year_from > year_to → swapped
7. `test_sanitize_empty_queries` — 0 queries → fallback query added
8. `test_compose_prompt_general` — domain="general" → base prompt only
9. `test_compose_prompt_materials` — domain="materials_science" → base + domain extra

**Verify**: `pytest tests/test_skills/test_query_builder.py -v` all pass.

---

## Task 10: Write Searcher tests [DONE]

**File**: `tests/test_skills/test_searcher.py` (NEW)

Tests (all with mocked SearchSource):
1. `test_search_single_source` — one source returns papers → returns them
2. `test_search_missing_source_fallback` — strategy asks for unavailable source → uses configured
3. `test_search_partial_failure` — one source fails → returns other's results
4. `test_search_empty_queries` — no queries → returns empty list
5. `test_search_all_fail` — all sources fail → returns empty list

**Verify**: `pytest tests/test_skills/test_searcher.py -v` all pass.

---

## Task 11: Write Deduplicator tests [DONE]

**File**: `tests/test_skills/test_deduplicator.py` (NEW)

Tests:
1. `test_dedup_by_doi` — same DOI (case-insensitive) → merged
2. `test_dedup_by_result_id` — same result_id in raw_data → merged
3. `test_dedup_by_url` — same full_text_url → merged
4. `test_dedup_by_normalized_title` — different casing/whitespace → merged
5. `test_dedup_llm_pass` — mock LLM groups semantic duplicates → merged
6. `test_dedup_llm_failure` — LLM fails → algorithm pass only, no crash
7. `test_dedup_no_llm` — constructed without LLM → algorithm only
8. `test_dedup_empty` — empty list → empty list
9. `test_dedup_single` — one paper → returns as-is
10. `test_merge_richest_record` — merged paper has best fields from group
11. `test_normalize_title` — various edge cases (punctuation, whitespace, unicode)

**Verify**: `pytest tests/test_skills/test_deduplicator.py -v` all pass.

---

## Task 12: Write RelevanceScorer tests [DONE]

**File**: `tests/test_skills/test_relevance_scorer.py` (NEW)

Tests (all with mocked LLM):
1. `test_score_basic` — 5 papers → 5 ScoredPapers with valid scores
2. `test_batching` — 25 papers, batch_size=10 → LLM called 3 times
3. `test_score_clamping` — LLM returns score=1.5 → clamped to 1.0
4. `test_missing_paper_default` — LLM returns 8 of 10 → 2 get default
5. `test_invalid_tag_filtering` — LLM returns invalid tags → filtered out
6. `test_llm_failure_fallback` — LLM raises error → default scores
7. `test_empty_input` — empty list → empty list, no LLM call
8. `test_truncation` — long title/snippet → truncated in user message

**Verify**: `pytest tests/test_skills/test_relevance_scorer.py -v` all pass.

---

## Task 13: Write ResultOrganizer tests [DONE]

**File**: `tests/test_skills/test_result_organizer.py` (NEW)

Tests:
1. `test_filter_by_relevance` — papers below threshold excluded
2. `test_sort_order` — verify multi-key sort
3. `test_facets_by_year` — correct year counts, None excluded
4. `test_facets_by_venue` — normalized venue counts
5. `test_facets_top_authors` — max 10, frequency sorted
6. `test_facets_key_themes` — max 8, stopwords excluded
7. `test_scored_to_paper_conversion` — all fields mapped correctly
8. `test_empty_input` — returns PaperCollection with empty papers
9. `test_all_filtered_out` — all below threshold → empty papers, total_found correct

**Verify**: `pytest tests/test_skills/test_result_organizer.py -v` all pass.

---

## Execution Order

```
Task 1 + Task 2 + Task 3    (prompts — independent of each other)
Task 4                       (QueryBuilder — depends on Task 1)
Task 5                       (Searcher — no prompt dependency)
Task 6                       (Deduplicator — depends on Task 3)
Task 7                       (RelevanceScorer — depends on Task 2)
Task 8                       (ResultOrganizer — no LLM dependency)
Task 9                       (QueryBuilder tests — depends on Task 4)
Task 10                      (Searcher tests — depends on Task 5)
Task 11                      (Deduplicator tests — depends on Task 6)
Task 12                      (Scorer tests — depends on Task 7)
Task 13                      (Organizer tests — depends on Task 8)
```

Parallelizable groups:
- Group A: Tasks 1, 2, 3 (prompts — fully independent)
- Group B: Tasks 4, 5, 8 (QueryBuilder, Searcher, ResultOrganizer — independent after prompts)
- Group C: Tasks 6, 7 (Deduplicator, Scorer — after prompts)
- Group D: Tasks 9, 10, 11, 12, 13 (all tests — after their respective skills)

All 13 tasks are mechanical. Zero decisions remain.
