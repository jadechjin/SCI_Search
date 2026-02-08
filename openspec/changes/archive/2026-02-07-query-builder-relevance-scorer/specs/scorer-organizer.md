# Spec: Relevance Scorer

## REQ-19: Basic Batch Scoring

**Given** 5 papers and a ParsedIntent,
**When** `RelevanceScorer.score(papers, intent)` is called,
**Then** returns 5 `ScoredPaper` objects, one per input paper.
**And** each has `relevance_score` in [0.0, 1.0], non-empty `relevance_reason`, valid `tags`.

## REQ-20: Batching

**Given** 25 papers and batch_size=10,
**When** `score()` is called,
**Then** LLM is called 3 times (batches of 10, 10, 5).

## REQ-21: Score Validation

**Given** LLM returns score=1.5 for a paper,
**When** scores are parsed,
**Then** score is clamped to 1.0.

**Given** LLM returns score=-0.3,
**Then** score is clamped to 0.0.

## REQ-22: Missing Paper Handling

**Given** LLM returns scores for only 8 of 10 papers in a batch,
**When** scores are parsed,
**Then** the 2 missing papers get default score (0.0, "Scoring unavailable", tags=[]).

## REQ-23: Invalid Tag Filtering

**Given** LLM returns tags=["method", "invalid_tag", "review"],
**When** scores are parsed,
**Then** only valid PaperTag enum values are kept: tags=["method", "review"].

## REQ-24: LLM Failure Fallback

**Given** LLM raises `LLMError` for a batch,
**When** `_score_batch()` is called,
**Then** all papers in that batch get default score (0.0, "Scoring unavailable").
**And** other batches are still processed normally.

## REQ-25: Empty Input

**Given** empty papers list,
**When** `score()` is called,
**Then** returns empty list (no LLM call).

## REQ-26: Truncation

**Given** a paper with title of 500 chars and snippet of 2000 chars,
**When** formatted for LLM prompt,
**Then** title is truncated to 200 chars, snippet to 500 chars.

---

## PBT Properties

### PROP-12: Score Bounds
**Invariant**: For all `ScoredPaper` in output, `0.0 <= relevance_score <= 1.0`.
**Falsification**: Mock LLM to return extreme scores; assert clamping works.

### PROP-13: Output Count Invariant
**Invariant**: `len(score(papers, intent)) == len(papers)`.
**Falsification**: Generate random paper lists of various sizes; assert output length matches input.

### PROP-14: Valid Tags Only
**Invariant**: All tags in any `ScoredPaper` are valid `PaperTag` enum members.
**Falsification**: Mock LLM to return random tag strings; assert only valid ones survive.

### PROP-15: Batch Count
**Invariant**: Number of LLM calls = ceil(len(papers) / batch_size).
**Falsification**: Track call count for various paper list sizes; assert matches formula.

---

# Spec: Result Organizer

## REQ-27: Relevance Filtering

**Given** papers with scores [0.8, 0.5, 0.2, 0.1] and min_relevance=0.3,
**When** `organize()` is called,
**Then** output contains 2 papers (0.8 and 0.5 only).

## REQ-28: Sort Order

**Given** papers: A(score=0.8, citations=10, year=2020), B(score=0.8, citations=20, year=2021),
**When** `organize()` is called,
**Then** B comes before A (same score, higher citations).

## REQ-29: Facets — by_year

**Given** papers with years [2020, 2020, 2021, 2022, None],
**When** `organize()` is called,
**Then** facets.by_year == {2020: 2, 2021: 1, 2022: 1} (None excluded).

## REQ-30: Facets — by_venue

**Given** papers with venues ["Nature", "nature", "Science", None],
**When** `organize()` is called,
**Then** facets.by_venue normalizes case: {"Nature": 2, "Science": 1}.

## REQ-31: Facets — top_authors

**Given** 20 papers with various authors,
**When** `organize()` is called,
**Then** facets.top_authors has at most 10 entries, sorted by frequency desc.

## REQ-32: Facets — key_themes

**Given** papers with titles containing common terms,
**When** `organize()` is called,
**Then** facets.key_themes has at most 8 entries.
**And** stopwords and short words (< 3 chars) are excluded.

## REQ-33: ScoredPaper → Paper Conversion

**Given** a `ScoredPaper` with all fields populated,
**When** converted to `Paper`,
**Then** all fields are mapped correctly (id, doi, title, authors, year, venue, etc.).

## REQ-34: Empty Input

**Given** empty papers list,
**When** `organize()` is called,
**Then** returns `PaperCollection` with empty papers list and zero-value facets.

## REQ-35: All Filtered Out

**Given** all papers have score < min_relevance,
**When** `organize()` is called,
**Then** returns `PaperCollection` with empty papers list.
**And** metadata.total_found reflects the original count (before filtering).

---

### PROP-16: Filter Monotonicity
**Invariant**: All papers in output have `relevance_score >= min_relevance`.
**Falsification**: Generate random scores and thresholds; assert all output papers pass threshold.

### PROP-17: Sort Stability
**Invariant**: Output is sorted by (relevance desc, citations desc, year desc, title asc).
**Falsification**: Generate random paper sets; verify sort order holds.

### PROP-18: Facet Consistency
**Invariant**: `sum(facets.by_year.values()) <= len(papers)` (some papers may have null year).
**Falsification**: Generate papers with mix of null/non-null years; assert facet sum ≤ paper count.

### PROP-19: Total Found Accuracy
**Invariant**: `metadata.total_found` equals the count of input papers (before filtering).
**Falsification**: Verify total_found matches input length regardless of filtering.
