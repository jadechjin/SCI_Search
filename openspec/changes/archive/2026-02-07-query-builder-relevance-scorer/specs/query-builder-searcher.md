# Spec: Query Builder

## REQ-1: Basic Query Generation

**Given** a valid `QueryBuilderInput` with intent (topic="LLM in medical imaging", concepts=["LLM", "medical imaging", "diagnosis"], intent_type=survey),
**When** `QueryBuilder.build(input)` is called,
**Then** returns a `SearchStrategy` with:
- `queries` is a non-empty list (1-4 items)
- Each query has non-empty `keywords`, `boolean_query`
- `sources` contains only available source names
- `filters` has valid constraints

## REQ-2: Source Restriction

**Given** `available_sources=["serpapi_scholar"]`,
**When** LLM returns `sources: ["semantic_scholar", "pubmed", "serpapi_scholar"]`,
**Then** the sanitized strategy has `sources == ["serpapi_scholar"]`.

**Given** LLM returns `sources: ["semantic_scholar"]` (none available),
**Then** sanitized strategy falls back to `sources == ["serpapi_scholar"]`.

## REQ-3: Iteration Support

**Given** `QueryBuilderInput` with `previous_strategies` (non-empty) and `user_feedback`,
**When** `build()` is called,
**Then** the user message to LLM includes formatted previous strategies and feedback.
**And** the generated strategy should differ from previous strategies (different boolean queries).

## REQ-4: Fallback on LLM Failure

**Given** the LLM raises `LLMError` or returns unparseable JSON,
**When** `build()` is called,
**Then** returns a deterministic fallback strategy:
- One query with `boolean_query` = intent concepts joined with " AND "
- `sources` = available_sources
- `filters` from intent.constraints

## REQ-5: Sanitization

**Given** LLM returns `year_from=2025, year_to=2020` (invalid range),
**When** `_sanitize()` is called,
**Then** swaps to `year_from=2020, year_to=2025`.

**Given** LLM returns 0 queries,
**Then** sanitize adds a fallback query from intent.concepts.

---

## PBT Properties

### PROP-1: Source Containment
**Invariant**: For any QueryBuilder output, `strategy.sources` is a subset of `available_sources`.
**Falsification**: Mock LLM to return random source names; assert output sources are always within allowed set.

### PROP-2: Non-Empty Queries
**Invariant**: `len(strategy.queries) >= 1` for any successful build().
**Falsification**: Mock LLM to return empty queries list; assert fallback adds at least one.

### PROP-3: Fallback Determinism
**Invariant**: `_fallback_strategy(input)` returns identical output for identical input.
**Falsification**: Call fallback twice with same input; assert results are equal.

### PROP-4: Year Range Validity
**Invariant**: If both year_from and year_to are set, `year_from <= year_to`.
**Falsification**: Generate random year pairs; assert sanitization always produces valid ranges.

---

# Spec: Searcher

## REQ-6: Single-Source Search

**Given** one configured source (SerpAPI) and a strategy with `sources=["serpapi_scholar"]`,
**When** `Searcher.search(strategy)` is called,
**Then** returns `list[RawPaper]` from SerpAPI.

## REQ-7: Missing Source Fallback

**Given** strategy.sources = `["semantic_scholar"]` (not configured),
**When** `Searcher.search(strategy)` is called,
**Then** uses all configured sources as fallback (SerpAPI).

## REQ-8: Partial Failure

**Given** 2 configured sources, source A succeeds with 10 papers, source B raises exception,
**When** `Searcher.search(strategy)` is called,
**Then** returns source A's 10 papers (not empty, not exception).

## REQ-9: Empty Strategy

**Given** strategy with empty `queries` list,
**When** `Searcher.search(strategy)` is called,
**Then** returns empty `list[RawPaper]`.

---

### PROP-5: Result Source Tag
**Invariant**: Every `RawPaper` returned has `source` matching one of the configured source names.
**Falsification**: Run search with various strategies; assert all paper.source values are valid.

### PROP-6: No Crash on Failure
**Invariant**: `search()` never raises exception; always returns a list (possibly empty).
**Falsification**: Mock sources to raise various exceptions; assert search returns list.
